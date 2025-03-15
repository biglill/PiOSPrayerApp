#!/usr/bin/env python3
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import time
from datetime import datetime, timedelta, timezone
import geocoder
import pygame
import json
import os
import logging

# Setup logging for debugging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

try:
    from praytimes import PrayTimes
except ImportError:
    messagebox.showerror("Missing Dependency",
                         "Please install the 'praytimes' package using pip (pip install praytimes)")
    raise

pygame.mixer.init()


###############################################################################
# Helper Functions
###############################################################################
def play_adhaan(audio_file):
    logging.debug(f"Attempting to play audio file: {audio_file}")
    try:
        pygame.mixer.music.load(audio_file)
        pygame.mixer.music.play()
    except Exception as e:
        logging.error(f"Error playing audio: {e}")


def get_location():
    try:
        logging.debug("Fetching location using geocoder...")
        g = geocoder.ip('me')
        latlng = g.latlng
        if latlng:
            logging.debug(f"Location found: {latlng}")
            return latlng[0], latlng[1]
        else:
            logging.warning("No location found via geocoder.")
    except Exception as e:
        logging.error(f"Error fetching location: {e}")
    logging.info("Using fallback location: Mecca (21.3891, 39.8579)")
    return 21.3891, 39.8579


def load_voice_database(db_path="adhan_votes.json"):
    if os.path.exists(db_path):
        try:
            logging.debug(f"Loading voice database from {db_path}...")
            with open(db_path, "r") as f:
                data = json.load(f)
                voices = data.get("voices", [])
                logging.debug(f"Loaded {len(voices)} voices from the database.")
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
            logging.debug("Sample voice database created.")
        except Exception as e:
            logging.error(f"Error writing sample voice database: {e}")
        return sample


def prayer_monitor(get_current_times, get_audio_file, get_adhaan_enabled):
    triggered = {}
    logging.debug("Starting prayer monitor thread.")
    while True:
        now_dt = datetime.now()
        now_str = now_dt.strftime("%H:%M")
        current_times = get_current_times()
        logging.debug(f"Current time: {now_str} | Prayer times: {current_times}")
        for prayer, time_str in current_times.items():
            # Only process the main five prayers
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


def convert_to_12h(time_str):
    """Convert a time string in 24-hour HH:MM format to 12-hour format with AM/PM."""
    try:
        t = datetime.strptime(time_str, "%H:%M")
        return t.strftime("%I:%M %p")
    except Exception as e:
        logging.error(f"Error converting time {time_str}: {e}")
        return time_str


###############################################################################
# Main App Class
###############################################################################
class AdhaanApp:
    def __init__(self, root):
        logging.debug("Initializing AdhaanApp...")
        self.root = root
        self.root.title("Adhaan Prayer Times")
        self.root.attributes("-fullscreen", True)
        self.root.configure(bg="#1A1A1A")  # Dark background

        self.lat, self.lng = get_location()
        # DST-adjusted timezone offset
        self.timezone_offset = datetime.now(timezone.utc).astimezone().utcoffset().total_seconds() / 3600
        logging.debug(f"Using location: ({self.lat}, {self.lng}), Timezone offset: {self.timezone_offset}")

        # Default calculation method is ISNA
        self.calc_method = tk.StringVar(value="ISNA")
        self.methods = ["ISNA", "MWL", "Egypt", "Makkah", "Karachi", "Tehran"]

        self.voice_database = load_voice_database()
        self.selected_voice = tk.StringVar()
        if self.voice_database:
            self.selected_voice.set(self.voice_database[0]["name"])
        else:
            self.selected_voice.set("None")

        # Only the main 5 prayers will trigger audio
        self.adhaan_enabled = {
            "fajr": True,
            "dhuhr": True,
            "asr": True,
            "maghrib": True,
            "isha": True
        }

        self.pray_times = {}
        self.is_testing = False  # For the test button state

        # Auto fetch interval in ms (default 5 minutes)
        self.auto_fetch_interval_var = tk.StringVar(value="5")
        self.auto_fetch_interval = int(self.auto_fetch_interval_var.get()) * 60000

        self.create_widgets()
        self.update_prayer_times()

        # Start background prayer monitor thread with adhaan-enabled check
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

        # Start auto-fetch scheduling
        self.schedule_refresh()

    def create_widgets(self):
        # Main container frame
        self.main_frame = tk.Frame(self.root, bg="#1A1A1A")
        self.main_frame.pack(expand=True, fill="both")

        # Left frame for prayer times
        self.left_frame = tk.Frame(self.main_frame, bg="#1A1A1A")
        self.left_frame.grid(row=0, column=0, sticky="nsew", padx=30, pady=30)

        # Right frame for options/info
        self.right_frame = tk.Frame(self.main_frame, bg="#1A1A1A")
        self.right_frame.grid(row=0, column=1, sticky="nsew", padx=30, pady=30)

        # Configure grid so both columns expand evenly
        self.main_frame.columnconfigure(0, weight=1)
        self.main_frame.columnconfigure(1, weight=1)

        ###############################################################################
        # Left Frame: Prayer Times and Bell Toggles
        ###############################################################################
        # We'll display 8 items: Fajr, Sunrise, Dhuhr, Asr, Maghrib, Isha, Midnight, Last Third.
        # For main prayers (Fajr, Dhuhr, Asr, Maghrib, Isha), include a bell toggle.
        self.prayer_order = [
            "Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha", "Midnight", "Last Third"
        ]
        self.labels = {}
        self.bell_buttons = {}
        for prayer in self.prayer_order:
            if prayer in ("Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"):
                # Create a frame for this row with label and bell button
                row_frame = tk.Frame(self.left_frame, bg="#1A1A1A")
                row_frame.pack(fill="x", pady=5, anchor="w")
                lbl = tk.Label(
                    row_frame,
                    text=f"{prayer}: --:--",
                    font=("Helvetica", 44),
                    bg="#1A1A1A",
                    fg="#F0F0F0",
                    anchor="w"
                )
                lbl.pack(side="left", fill="x", expand=True)
                self.labels[prayer] = lbl
                # Create bell toggle button; initial icon "🔔" (enabled)
                btn = tk.Button(
                    row_frame,
                    text="🔔",
                    font=("Helvetica", 44),
                    bg="#1A1A1A",
                    fg="#F0F0F0",
                    bd=0,
                    highlightthickness=0,
                    command=lambda p=prayer: self.toggle_adhaan(p)
                )
                btn.pack(side="right")
                self.bell_buttons[prayer.lower()] = btn
            else:
                # For non-main items, just a label
                lbl = tk.Label(
                    self.left_frame,
                    text=f"{prayer}: --:--",
                    font=("Helvetica", 44),
                    bg="#1A1A1A",
                    fg="#F0F0F0",
                    anchor="w"
                )
                lbl.pack(fill="x", pady=5, anchor="w")
                self.labels[prayer] = lbl

        ###############################################################################
        # Right Frame: Options and Info
        ###############################################################################
        # Location Label
        location_text = f"Location: {self.lat:.4f}, {self.lng:.4f}"
        self.location_label = tk.Label(
            self.right_frame,
            text=location_text,
            font=("Helvetica", 18),
            bg="#1A1A1A",
            fg="#F0F0F0"
        )
        self.location_label.pack(pady=10, anchor="nw")

        # Calculation Method Dropdown
        method_frame = tk.Frame(self.right_frame, bg="#1A1A1A")
        method_frame.pack(pady=10, anchor="nw")
        tk.Label(method_frame, text="Calculation Method:", font=("Helvetica", 16),
                 bg="#1A1A1A", fg="#F0F0F0").pack(side="left", padx=5)
        method_menu = tk.OptionMenu(method_frame, self.calc_method, *self.methods, command=self.on_method_change)
        method_menu.config(font=("Helvetica", 14), bg="#333333", fg="#F0F0F0", highlightthickness=0)
        method_menu["menu"].config(bg="#333333", fg="#F0F0F0")
        method_menu.pack(side="left", padx=5)

        # Adhaan Voice Selection Dropdown
        voice_frame = tk.Frame(self.right_frame, bg="#1A1A1A")
        voice_frame.pack(pady=10, anchor="nw")
        tk.Label(voice_frame, text="Select Adhaan Voice:", font=("Helvetica", 16),
                 bg="#1A1A1A", fg="#F0F0F0").pack(side="left", padx=5)
        voice_options = [f"{v['name']} ({v['votes']} votes)" for v in self.voice_database] if self.voice_database else [
            "None"]
        self.voice_menu = tk.StringVar()
        self.voice_menu.set(voice_options[0])
        option_menu = tk.OptionMenu(voice_frame, self.voice_menu, *voice_options)
        option_menu.config(font=("Helvetica", 14), bg="#333333", fg="#F0F0F0", highlightthickness=0)
        option_menu["menu"].config(bg="#333333", fg="#F0F0F0")
        option_menu.pack(side="left", padx=5)

        # Option to select a custom voice file
        manual_frame = tk.Frame(self.right_frame, bg="#1A1A1A")
        manual_frame.pack(pady=10, anchor="nw")
        self.manual_voice_label = tk.Label(manual_frame, text="Or select a custom Adhaan voice:",
                                           font=("Helvetica", 16), bg="#1A1A1A", fg="#F0F0F0")
        self.manual_voice_label.pack(side="left", padx=5)
        select_voice_button = tk.Button(manual_frame, text="Select File", font=("Helvetica", 14),
                                        bg="#333333", fg="#F0F0F0",
                                        command=self.select_voice_file, highlightthickness=0)
        select_voice_button.pack(side="left", padx=5)

        # Adhaan Test Button
        self.test_button = tk.Button(
            self.right_frame,
            text="Test Adhaan",
            font=("Helvetica", 14),
            bg="#333333",
            fg="#F0F0F0",
            command=self.toggle_test_adhaan,
            highlightthickness=0
        )
        self.test_button.pack(pady=10, anchor="nw")

        # Prayer Time Fetch Options Section
        fetch_frame = tk.Frame(self.right_frame, bg="#1A1A1A")
        fetch_frame.pack(pady=10, anchor="nw")
        tk.Label(fetch_frame, text="Prayer Time Fetch Options:", font=("Helvetica", 16),
                 bg="#1A1A1A", fg="#F0F0F0").pack(side="top", padx=5, anchor="w")
        inner_fetch = tk.Frame(fetch_frame, bg="#1A1A1A")
        inner_fetch.pack(side="top", padx=5, pady=5, anchor="w")
        # Manual Fetch Button
        fetch_button = tk.Button(inner_fetch, text="Fetch Now", font=("Helvetica", 14),
                                 bg="#333333", fg="#F0F0F0", command=self.update_prayer_times, highlightthickness=0)
        fetch_button.pack(side="left", padx=5)
        # Auto Fetch Interval Dropdown
        tk.Label(inner_fetch, text="Auto Fetch Interval:", font=("Helvetica", 14),
                 bg="#1A1A1A", fg="#F0F0F0").pack(side="left", padx=5)
        auto_fetch_options = ["1", "2", "5", "10", "15", "30"]
        self.auto_fetch_interval_var = tk.StringVar(value="5")
        auto_fetch_menu = tk.OptionMenu(inner_fetch, self.auto_fetch_interval_var, *auto_fetch_options,
                                        command=self.on_interval_change)
        auto_fetch_menu.config(font=("Helvetica", 14), bg="#333333", fg="#F0F0F0", highlightthickness=0)
        auto_fetch_menu["menu"].config(bg="#333333", fg="#F0F0F0")
        auto_fetch_menu.pack(side="left", padx=5)
        tk.Label(inner_fetch, text="minutes", font=("Helvetica", 14), bg="#1A1A1A", fg="#F0F0F0").pack(side="left",
                                                                                                       padx=5)

        # Exit Button
        exit_button = tk.Button(
            self.right_frame,
            text="Exit",
            font=("Helvetica", 14),
            bg="#333333",
            fg="#F0F0F0",
            command=self.root.destroy,
            highlightthickness=0
        )
        exit_button.pack(pady=40, anchor="nw")

    ###############################################################################
    # Event Handlers and Logic
    ###############################################################################
    def on_method_change(self, _):
        logging.debug(f"Calculation method changed to: {self.calc_method.get()}")
        self.update_prayer_times()

    def on_interval_change(self, value):
        try:
            minutes = int(value)
            self.auto_fetch_interval = minutes * 60000
            logging.debug(f"Auto fetch interval updated to {self.auto_fetch_interval} ms")
        except Exception as e:
            logging.error(f"Error parsing auto fetch interval: {e}")

    def select_voice_file(self):
        file_path = filedialog.askopenfilename(
            title="Select Adhaan Audio File",
            filetypes=[("Audio Files", "*.mp3 *.wav *.ogg"), ("All Files", "*.*")]
        )
        if file_path:
            logging.debug(f"Manual voice file selected: {file_path}")
            self.voice_menu.set(f"Custom: {os.path.basename(file_path)}")
            self.manual_voice_file = file_path
        else:
            logging.debug("No manual voice file selected.")
            self.manual_voice_file = None

    def get_audio_file(self):
        if hasattr(self, "manual_voice_file") and self.manual_voice_file:
            logging.debug(f"Using manual voice file: {self.manual_voice_file}")
            return self.manual_voice_file
        selected = self.voice_menu.get()
        if selected.startswith("Custom:"):
            return None
        voice_name = selected.split(" (")[0]
        for voice in self.voice_database:
            if voice["name"] == voice_name:
                logging.debug(f"Selected voice from database: {voice}")
                return voice["file"]
        logging.warning("No matching voice found in database.")
        return None

    def toggle_test_adhaan(self):
        if not self.is_testing:
            audio_file = self.get_audio_file()
            if audio_file:
                play_adhaan(audio_file)
                self.is_testing = True
                self.test_button.config(text="Stop Test")
            else:
                messagebox.showwarning("No Audio File", "Please select an Adhaan audio file to test.")
        else:
            pygame.mixer.music.stop()
            self.is_testing = False
            self.test_button.config(text="Test Adhaan")

    def toggle_adhaan(self, prayer):
        key = prayer.lower()
        current = self.adhaan_enabled.get(key, True)
        new_value = not current
        self.adhaan_enabled[key] = new_value
        btn = self.bell_buttons.get(key)
        if btn:
            btn.config(text="🔔" if new_value else "🔕")
        logging.debug(f"Adhaan for {prayer} set to {'enabled' if new_value else 'disabled'}.")

    def update_prayer_times(self):
        logging.debug("Updating prayer times...")
        pt = PrayTimes(method=self.calc_method.get())
        logging.debug(f"Using calculation method: {self.calc_method.get()}")
        today = datetime.now()
        date_tuple = [today.year, today.month, today.day]
        try:
            self.pray_times = pt.getTimes(date_tuple, (self.lat, self.lng), self.timezone_offset)
            logging.info(f"Prayer times updated: {self.pray_times}")
        except Exception as e:
            logging.error(f"Error calculating prayer times: {e}")
            self.pray_times = {}

        # Compute "Last Third" of the night
        tomorrow = today + timedelta(days=1)
        tomorrow_tuple = [tomorrow.year, tomorrow.month, tomorrow.day]
        try:
            tomorrow_times = pt.getTimes(tomorrow_tuple, (self.lat, self.lng), self.timezone_offset)
            sunset_dt = datetime.combine(today.date(),
                                         datetime.strptime(self.pray_times.get("sunset", "00:00"), "%H:%M").time())
            tomorrow_fajr_dt = datetime.combine(tomorrow.date(),
                                                datetime.strptime(tomorrow_times.get("fajr", "00:00"), "%H:%M").time())
            night_duration = (tomorrow_fajr_dt - sunset_dt).total_seconds()
            last_third_dt = sunset_dt + timedelta(seconds=(2 / 3) * night_duration)
            self.pray_times["lastthird"] = last_third_dt.strftime("%H:%M")
            logging.info(f"Last Third calculated as: {self.pray_times['lastthird']}")
        except Exception as e:
            logging.error(f"Error calculating last third of the night: {e}")
            self.pray_times["lastthird"] = "--:--"

        self.update_display()

    def update_display(self):
        # Update prayer time labels in 12-hour format
        for prayer in self.prayer_order:
            key = prayer.lower().replace(" ", "")
            if prayer == "Last Third":
                key = "lastthird"
            raw_time = self.pray_times.get(key, "--:--")
            display_time = convert_to_12h(raw_time) if raw_time != "--:--" else raw_time
            self.labels[prayer].config(text=f"{prayer}: {display_time}")
        logging.debug("Display updated with new prayer times.")

    def get_prayer_times(self):
        return self.pray_times

    def schedule_refresh(self):
        logging.debug("Scheduling prayer times refresh...")
        self.update_prayer_times()
        self.root.after(self.auto_fetch_interval, self.schedule_refresh)


###############################################################################
# Entry Point
###############################################################################
def main():
    logging.debug("Starting the Adhaan App...")
    root = tk.Tk()
    app = AdhaanApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()