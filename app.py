#!/usr/bin/env python3
import sys
import threading
import time
import logging
import json
import os
from datetime import datetime, timedelta, timezone

import geocoder
import pygame

# PyQt5 imports for modern UI
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QLineEdit, QComboBox, QCheckBox,
    QFileDialog, QMessageBox, QVBoxLayout, QHBoxLayout, QGroupBox, QGridLayout, QSpacerItem, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer

try:
    from praytimes import PrayTimes
except ImportError as e:
    logging.error("Missing dependency 'praytimes'. Install it using pip (pip install praytimes)")
    sys.exit(1)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

pygame.mixer.init()


def play_adhaan(audio_file):
    logging.info(f"Playing audio file: {audio_file}")
    try:
        pygame.mixer.music.load(audio_file)
        pygame.mixer.music.play()
    except Exception as e:
        logging.error(f"Error playing audio: {e}")


def convert_to_12h(time_str):
    try:
        t = datetime.strptime(time_str, "%H:%M")
        return t.strftime("%I:%M %p")
    except Exception as e:
        logging.error(f"Error converting time {time_str}: {e}")
        return time_str


def load_voice_database(db_path="adhan_votes.json"):
    if os.path.exists(db_path):
        try:
            logging.info(f"Loading voice database from {db_path}...")
            with open(db_path, "r") as f:
                data = json.load(f)
                voices = data.get("voices", [])
                logging.info(f"Loaded {len(voices)} voices.")
                return voices
        except Exception as e:
            logging.error(f"Error loading voice database: {e}")
            return []
    else:
        logging.info(f"Voice database file {db_path} not found. Creating sample database...")
        sample = [
            {"name": "Mishary Rashid Alafasy", "votes": 250, "file": "adhan_alafasy.mp3"},
            {"name": "Abdul Basit", "votes": 300, "file": "adhan_basit.mp3"},
            {"name": "Saad Al-Ghamdi", "votes": 200, "file": "adhan_ghamdi.mp3"}
        ]
        try:
            with open(db_path, "w") as f:
                json.dump({"voices": sample}, f, indent=4)
            logging.info("Sample voice database created.")
        except Exception as e:
            logging.error(f"Error writing sample voice database: {e}")
        return sample


def prayer_monitor(get_current_times, get_audio_file, get_adhaan_enabled):
    triggered = {}
    logging.info("Starting prayer monitor thread.")
    while True:
        now_dt = datetime.now()
        now_str = now_dt.strftime("%H:%M")
        current_times = get_current_times()
        for prayer, time_str in current_times.items():
            if prayer not in ("fajr", "dhuhr", "asr", "maghrib", "isha"):
                continue
            if now_str == time_str and triggered.get(prayer) != now_str:
                if get_adhaan_enabled(prayer):
                    audio_file = get_audio_file()
                    if audio_file:
                        play_adhaan(audio_file)
                    else:
                        logging.warning("No Adhaan audio file selected.")
                triggered[prayer] = now_str
        time.sleep(10)


class AdhaanApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Adhaan Prayer Times")
        self.setGeometry(100, 100, 1280, 720)
        self.setStyleSheet("""
            QWidget { background-color: #121212; color: #FFFFFF; font-family: 'Segoe UI'; }
            QPushButton { background-color: #333333; border: none; padding: 10px; }
            QPushButton:hover { background-color: #444444; }
            QLineEdit { background-color: #333333; padding: 5px; border: 1px solid #555555; }
            QComboBox { background-color: #333333; padding: 5px; border: 1px solid #555555; }
            QCheckBox { padding: 5px; }
            QGroupBox { margin-top: 20px; border: 1px solid #333333; border-radius: 5px; padding: 10px; }
        """)

        # Modern fonts (used via stylesheet and widget font settings)
        self.font_large = "44pt 'Segoe UI'"
        self.font_medium = "18pt 'Segoe UI'"
        self.font_small = "14pt 'Segoe UI'"

        # Location settings
        self.auto_location_enabled = True
        self.zip_code = ""
        self.region = "USA"  # Default region
        self.lat = 21.3891
        self.lng = 39.8579
        self.timezone_offset = datetime.now(timezone.utc).astimezone().utcoffset().total_seconds() / 3600

        self.calc_method = "ISNA"
        self.methods = ["ISNA", "MWL", "Egypt", "Makkah", "Karachi", "Tehran"]

        self.voice_database = load_voice_database()
        self.selected_voice = self.voice_database[0]["name"] if self.voice_database else "None"

        self.adhaan_enabled = {
            "fajr": True,
            "dhuhr": True,
            "asr": True,
            "maghrib": True,
            "isha": True
        }

        self.pray_times = {}
        self.is_testing = False
        self.auto_fetch_interval = 5 * 60000  # default auto-refresh interval in ms

        self.init_ui()
        self.update_prayer_times()

        # Start background prayer monitor thread
        self.monitor_thread = threading.Thread(
            target=prayer_monitor,
            args=(
                self.get_prayer_times,
                self.get_audio_file,
                lambda prayer: self.adhaan_enabled.get(prayer, False)
            )
        )
        self.monitor_thread.daemon = True
        self.monitor_thread.start()

        # Start auto-refresh timer for prayer times
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.update_prayer_times)
        self.refresh_timer.start(self.auto_fetch_interval)

        # Auto-update location on startup if enabled
        if self.auto_location_enabled:
            self.update_location()

    def init_ui(self):
        main_layout = QHBoxLayout(self)

        # Left side: Prayer Times Display
        self.prayer_order = ["Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha", "Midnight", "Last Third"]
        left_layout = QVBoxLayout()
        self.prayer_labels = {}
        self.bell_buttons = {}
        for prayer in self.prayer_order:
            h_layout = QHBoxLayout()
            lbl = QLabel(f"{prayer}: --:--")
            lbl.setStyleSheet("font-size: 44pt;")
            lbl.setAlignment(Qt.AlignLeft)
            h_layout.addWidget(lbl, 1)
            self.prayer_labels[prayer] = lbl
            if prayer.lower() in ("fajr", "dhuhr", "asr", "maghrib", "isha"):
                btn = QPushButton("🔔")
                btn.setStyleSheet("font-size: 44pt; background-color: #121212;")
                btn.clicked.connect(lambda checked, p=prayer: self.toggle_adhaan(p))
                h_layout.addWidget(btn)
                self.bell_buttons[prayer.lower()] = btn
            left_layout.addLayout(h_layout)

        # Right side: Options & Settings
        right_layout = QVBoxLayout()

        # Location Settings GroupBox
        loc_group = QGroupBox("Location Settings")
        loc_layout = QGridLayout()
        # Automatic location checkbox
        self.auto_loc_checkbox = QCheckBox("Automatic Location")
        self.auto_loc_checkbox.setChecked(self.auto_location_enabled)
        self.auto_loc_checkbox.stateChanged.connect(self.update_location_fields_state)
        loc_layout.addWidget(self.auto_loc_checkbox, 0, 0, 1, 2)
        # ZIP Code Entry
        loc_layout.addWidget(QLabel("ZIP Code:"), 1, 0)
        self.zip_edit = QLineEdit(self.zip_code)
        loc_layout.addWidget(self.zip_edit, 1, 1)
        # Region Entry
        loc_layout.addWidget(QLabel("Region:"), 2, 0)
        self.region_edit = QLineEdit(self.region)
        loc_layout.addWidget(self.region_edit, 2, 1)
        # Latitude Entry
        loc_layout.addWidget(QLabel("Latitude:"), 3, 0)
        self.latitude_edit = QLineEdit(str(self.lat))
        loc_layout.addWidget(self.latitude_edit, 3, 1)
        # Longitude Entry
        loc_layout.addWidget(QLabel("Longitude:"), 4, 0)
        self.longitude_edit = QLineEdit(str(self.lng))
        loc_layout.addWidget(self.longitude_edit, 4, 1)
        # Update Location Button
        self.update_loc_button = QPushButton("Update Location")
        self.update_loc_button.clicked.connect(self.update_location)
        loc_layout.addWidget(self.update_loc_button, 5, 0, 1, 2)
        loc_group.setLayout(loc_layout)
        right_layout.addWidget(loc_group)

        # Current Location Display
        self.location_label = QLabel(f"Location: {self.lat:.4f}, {self.lng:.4f}")
        self.location_label.setStyleSheet("font-size: 18pt;")
        right_layout.addWidget(self.location_label)

        # Calculation Method Selection
        calc_group = QGroupBox("Calculation Method")
        calc_layout = QHBoxLayout()
        calc_layout.addWidget(QLabel("Method:"))
        self.method_combo = QComboBox()
        self.method_combo.addItems(self.methods)
        self.method_combo.setCurrentText(self.calc_method)
        self.method_combo.currentTextChanged.connect(self.on_method_change)
        calc_layout.addWidget(self.method_combo)
        calc_group.setLayout(calc_layout)
        right_layout.addWidget(calc_group)

        # Voice Selection Section
        voice_group = QGroupBox("Adhaan Voice Selection")
        voice_layout = QHBoxLayout()
        voice_layout.addWidget(QLabel("Select Voice:"))
        self.voice_combo = QComboBox()
        voice_options = [f"{v['name']} ({v['votes']} votes)" for v in self.voice_database] if self.voice_database else [
            "None"]
        self.voice_combo.addItems(voice_options)
        voice_layout.addWidget(self.voice_combo)
        self.custom_voice_button = QPushButton("Select Custom File")
        self.custom_voice_button.clicked.connect(self.select_voice_file)
        voice_layout.addWidget(self.custom_voice_button)
        voice_group.setLayout(voice_layout)
        right_layout.addWidget(voice_group)

        # Test Adhaan Button
        self.test_button = QPushButton("Test Adhaan")
        self.test_button.clicked.connect(self.toggle_test_adhaan)
        right_layout.addWidget(self.test_button)

        # Prayer Time Fetch Options
        fetch_group = QGroupBox("Prayer Time Fetch Options")
        fetch_layout = QHBoxLayout()
        self.fetch_now_button = QPushButton("Fetch Now")
        self.fetch_now_button.clicked.connect(self.update_prayer_times)
        fetch_layout.addWidget(self.fetch_now_button)
        fetch_layout.addWidget(QLabel("Auto Fetch Interval (min):"))
        self.interval_combo = QComboBox()
        self.interval_combo.addItems(["1", "2", "5", "10", "15", "30"])
        self.interval_combo.setCurrentText("5")
        self.interval_combo.currentTextChanged.connect(self.on_interval_change)
        fetch_layout.addWidget(self.interval_combo)
        fetch_group.setLayout(fetch_layout)
        right_layout.addWidget(fetch_group)

        # Spacer to push Exit button to bottom
        right_layout.addItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))

        # Exit Button
        self.exit_button = QPushButton("Exit")
        self.exit_button.clicked.connect(self.close)
        right_layout.addWidget(self.exit_button)

        main_layout.addLayout(left_layout, 2)
        main_layout.addLayout(right_layout, 1)

        self.setLayout(main_layout)
        self.update_location_fields_state()

    def update_location_fields_state(self):
        # Enable or disable ZIP, Region, Latitude and Longitude fields based on auto location setting
        auto = self.auto_loc_checkbox.isChecked()
        self.zip_edit.setEnabled(not auto)
        self.region_edit.setEnabled(not auto)
        self.latitude_edit.setEnabled(not auto)
        self.longitude_edit.setEnabled(not auto)
        self.auto_location_enabled = auto

    def update_location(self):
        logging.info("Updating location...")
        if self.auto_location_enabled:
            try:
                # Use ipinfo for a potentially more accurate IP-based lookup
                g = geocoder.ipinfo('me')
                latlng = g.latlng
                if latlng:
                    self.lat, self.lng = latlng[0], latlng[1]
                else:
                    logging.warning("Automatic location failed. Using fallback.")
                    self.lat, self.lng = 21.3891, 39.8579
            except Exception as e:
                logging.error(f"Error fetching automatic location: {e}")
                self.lat, self.lng = 21.3891, 39.8579
        else:
            # Try to use manually provided latitude and longitude
            try:
                manual_lat = float(self.latitude_edit.text().strip())
                manual_lng = float(self.longitude_edit.text().strip())
                self.lat, self.lng = manual_lat, manual_lng
            except Exception as e:
                # Fallback to ZIP/Region lookup if manual conversion fails
                zip_code = self.zip_edit.text().strip()
                region = self.region_edit.text().strip()
                if zip_code:
                    query = f"{zip_code}, {region}" if region else zip_code
                    logging.info(f"Fetching location for query: {query}")
                    try:
                        g = geocoder.osm(query, params={'email': 'biglildev@gmail.com'})
                        latlng = g.latlng
                        if latlng:
                            self.lat, self.lng = latlng[0], latlng[1]
                        else:
                            logging.warning("Location lookup failed. Using fallback.")
                            self.lat, self.lng = 21.3891, 39.8579
                    except Exception as e:
                        logging.error(f"Error fetching location for query '{query}': {e}")
                        self.lat, self.lng = 21.3891, 39.8579
                else:
                    logging.info("No valid coordinates provided. Using fallback location.")
                    self.lat, self.lng = 21.3891, 39.8579
        # Update manual fields with current values
        self.latitude_edit.setText(str(self.lat))
        self.longitude_edit.setText(str(self.lng))
        self.location_label.setText(f"Location: {self.lat:.4f}, {self.lng:.4f}")
        self.update_prayer_times()

    def on_method_change(self, method):
        self.calc_method = method
        logging.info(f"Calculation method changed to: {self.calc_method}")
        self.update_prayer_times()

    def on_interval_change(self, value):
        try:
            minutes = int(value)
            self.auto_fetch_interval = minutes * 60000
            self.refresh_timer.start(self.auto_fetch_interval)
            logging.info(f"Auto fetch interval updated to {self.auto_fetch_interval} ms")
        except Exception as e:
            logging.error(f"Error parsing auto fetch interval: {e}")

    def select_voice_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Adhaan Audio File",
            "",
            "Audio Files (*.mp3 *.wav *.ogg);;All Files (*)"
        )
        if file_path:
            logging.info(f"Manual voice file selected: {file_path}")
            self.voice_combo.clear()
            self.voice_combo.addItem(f"Custom: {os.path.basename(file_path)}")
            self.manual_voice_file = file_path
        else:
            logging.info("No manual voice file selected.")
            self.manual_voice_file = None

    def get_audio_file(self):
        if hasattr(self, "manual_voice_file") and self.manual_voice_file:
            return self.manual_voice_file
        selected = self.voice_combo.currentText()
        if selected.startswith("Custom:"):
            return None
        voice_name = selected.split(" (")[0]
        for voice in self.voice_database:
            if voice["name"] == voice_name:
                return voice["file"]
        logging.warning("No matching voice found in database.")
        return None

    def toggle_test_adhaan(self):
        if not self.is_testing:
            audio_file = self.get_audio_file()
            if audio_file:
                play_adhaan(audio_file)
                self.is_testing = True
                self.test_button.setText("Stop Test")
            else:
                QMessageBox.warning(self, "No Audio File", "Please select an Adhaan audio file to test.")
        else:
            pygame.mixer.music.stop()
            self.is_testing = False
            self.test_button.setText("Test Adhaan")

    def toggle_adhaan(self, prayer):
        key = prayer.lower()
        current = self.adhaan_enabled.get(key, True)
        new_value = not current
        self.adhaan_enabled[key] = new_value
        btn = self.bell_buttons.get(key)
        if btn:
            btn.setText("🔔" if new_value else "🔕")
        logging.info(f"Adhaan for {prayer} {'enabled' if new_value else 'disabled'}.")

    def update_prayer_times(self):
        logging.info("Updating prayer times...")
        pt = PrayTimes(method=self.calc_method)
        today = datetime.now()
        date_tuple = [today.year, today.month, today.day]
        try:
            self.pray_times = pt.getTimes(date_tuple, (self.lat, self.lng), self.timezone_offset)
            logging.info(f"Prayer times: {self.pray_times}")
        except Exception as e:
            logging.error(f"Error calculating prayer times: {e}")
            self.pray_times = {}
        try:
            tomorrow = today + timedelta(days=1)
            tomorrow_tuple = [tomorrow.year, tomorrow.month, tomorrow.day]
            tomorrow_times = pt.getTimes(tomorrow_tuple, (self.lat, self.lng), self.timezone_offset)
            sunset_str = self.pray_times.get("sunset", "00:00")
            sunset_dt = datetime.combine(today.date(), datetime.strptime(sunset_str, "%H:%M").time())
            tomorrow_fajr_str = tomorrow_times.get("fajr", "00:00")
            tomorrow_fajr_dt = datetime.combine(tomorrow.date(), datetime.strptime(tomorrow_fajr_str, "%H:%M").time())
            night_duration = (tomorrow_fajr_dt - sunset_dt).total_seconds()
            last_third_dt = sunset_dt + timedelta(seconds=(2 / 3) * night_duration)
            self.pray_times["lastthird"] = last_third_dt.strftime("%H:%M")
            logging.info(f"Last Third: {self.pray_times['lastthird']}")
        except Exception as e:
            logging.error(f"Error calculating last third: {e}")
            self.pray_times["lastthird"] = "--:--"
        self.update_display()

    def update_display(self):
        for prayer in self.prayer_order:
            key = prayer.lower().replace(" ", "")
            if prayer == "Last Third":
                key = "lastthird"
            raw_time = self.pray_times.get(key, "--:--")
            display_time = convert_to_12h(raw_time) if raw_time != "--:--" else raw_time
            if prayer in self.prayer_labels:
                self.prayer_labels[prayer].setText(f"{prayer}: {display_time}")
        logging.info("Display updated.")

    def get_prayer_times(self):
        return self.pray_times


def main():
    app = QApplication(sys.argv)
    window = AdhaanApp()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    while True:
        try:
            main()
        except Exception as e:
            logging.error("Unhandled exception. Restarting in 5 seconds...", exc_info=True)
            time.sleep(5)
