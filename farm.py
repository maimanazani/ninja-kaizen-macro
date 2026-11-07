import base64
import json
import ctypes
import msvcrt
import os
import sys
from ctypes import wintypes as wt
from pathlib import Path
import time
import threading

import cv2
import numpy as np
from PIL import ImageGrab

WIDTH, HEIGHT = 960, 540
SKILL_POINTS = [(235, 421), (287, 421), (341, 421), (393, 421),
                (568, 421), (622, 421), (675, 421)]
REF_DIR = Path(__file__).with_name("refs")
SETTINGS = Path(__file__).with_name("mission.json")
GRADE_BUTTONS = {"A": (681, 317), "B": (681, 383), "C": (681, 450)}
# Known missions: (grade, name, page, row) — row "1" top, "2" middle, "3" bottom.
MISSIONS = [
    ("A", "Concern of Norobi", "3/10", "1"),
    ("A", "The Antique Vase", "3/10", "2"),
    ("B", "Where are the Hooligans?", "3/10", "1"),
    ("B", "Mountain Bandits", "10/10", "1"),
    ("C", "Hardworking Student", "3/18", "1"),
    ("C", "Blacksmith's Request", "3/18", "2"),
    ("C", "Confidential Document", "3/18", "3"),
    ("C", "Weaver's Request", "6/18", "1"),
    ("C", "Conflicts with the Samurai", "6/18", "2"),
    ("C", "Yuna's Request", "6/18", "3"),
    ("C", "Grandmother's Gift", "9/18", "1"),
    ("C", "Find the Antidote", "9/18", "2"),
    ("C", "Enemies for Interrogation", "9/18", "3"),
    ("C", "The Mysterious Light", "12/18", "1"),
    ("C", "The Desert Bandits", "12/18", "2"),
    ("C", "Escort the Merchant", "12/18", "3"),
    ("C", "Explosive Mines", "15/18", "1"),
    ("C", "It's the Samurai Again", "15/18", "2"),
    ("C", "Assassinate the Ninja Spy Leader", "15/18", "3"),
    ("C", "Sea Robbers are Back", "18/18", "1"),
    ("C", "Clear Main Artery", "18/18", "2"),
    ("C", "Threatening Soil Village", "18/18", "3"),
]
CALIBRATION_BOXES = {
    "Mission list": (510, 55, 850, 111),
    "Page counter": (759, 409, 832, 438),
}
ROW_CENTERS = (166, 251, 336)
COMBAT_VARIANTS = ("Attack", "Attack label", "Dodge", "Turn timer")
u = ctypes.WinDLL("user32", use_last_error=True)
u.SetProcessDPIAware()
for name, arguments, result in [
    ("GetForegroundWindow", [], wt.HWND),
    ("GetWindowTextW", [wt.HWND, wt.LPWSTR, ctypes.c_int], ctypes.c_int),
    ("GetClientRect", [wt.HWND, ctypes.POINTER(wt.RECT)], wt.BOOL),
    ("ClientToScreen", [wt.HWND, ctypes.POINTER(wt.POINT)], wt.BOOL),
    ("WindowFromPoint", [wt.POINT], wt.HWND),
    ("GetAncestor", [wt.HWND, wt.UINT], wt.HWND),
]:
    function = getattr(u, name)
    function.argtypes, function.restype = arguments, result

# Template centers in the normalized game area.
MARKERS = {
    "Battle": (716, 386),
    "Next page": (854, 423),
    "Start mission": (846, 420),
    "Continue": (480, 429),
    "Attack": (453, 394),
    "Attack label": (453, 415),
    "Dodge": (505, 395),
    "Turn timer": (308, 325),
    "Mission Success": (480, 63),
    "Claim": (480, 447),
    "Claim plain": (480, 447),
    "Level Up": (472, 134),
    "Level Up checkmark": (858, 363),
}
CLICK_POINTS = {
    "Battle": (716, 386),
    "Start mission": (846, 420),
    "Continue": (480, 380),
}


class MenuRequested(RuntimeError):
    pass


def title(hwnd):
    result = ctypes.create_unicode_buffer(256)
    u.GetWindowTextW(hwnd, result, len(result))
    return result.value


def bounds(hwnd):
    rect, origin = wt.RECT(), wt.POINT()
    if not u.GetClientRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("Could not read the game window size.")
    if not u.ClientToScreen(hwnd, ctypes.byref(origin)):
        raise RuntimeError("Could not locate the game on the desktop.")
    return origin.x, origin.y, origin.x + rect.right, origin.y + rect.bottom


def pressed(key):
    return bool(u.GetAsyncKeyState(key) & 0x8000)


escape_request = threading.Event()


def escape_requested():
    return escape_request.is_set() or pressed(0x1B)


def watch_escape(stop):
    while not stop.is_set():
        if pressed(0x1B):
            escape_request.set()
            return
        stop.wait(0.01)


def normalize(picture):
    return cv2.resize(np.asarray(picture), (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA)


class Farm:
    def __init__(self, hwnd, settings=None):
        self.settings = settings
        self.attach(hwnd)
        self.reset_mission()
        self.markers = MARKERS.copy()
        self.refs = {name: [self.read_reference((REF_DIR / f"{name}.png").read_bytes())]
                     for name in self.markers}
        for name in COMBAT_VARIANTS:
            self.refs[name].append(self.read_reference((REF_DIR / f"{name} snowy.png").read_bytes()))
        if settings:
            grade = settings["grade"]
            self.markers["Grade button"] = GRADE_BUTTONS[grade]
            self.refs["Grade button"] = [self.read_reference((REF_DIR / f"Grade {grade}.png").read_bytes())]
            for name, box in calibration_boxes(settings["row"]).items():
                left, top, right, bottom = box
                self.markers[name] = ((left + right) // 2, (top + bottom) // 2)
                self.refs[name] = [self.read_reference(base64.b64decode(settings["refs"][name]))]

    def attach(self, hwnd):
        box = bounds(hwnd)
        left, top, right, bottom = box
        width, height = right - left, bottom - top
        if width < 800 or abs(width / max(1, height) - 16 / 9) > 0.04:
            raise RuntimeError("Use a visible 16:9 window such as 960 x 540.")
        self.hwnd, self.box = hwnd, box
        self.width, self.height = width, height

    def reset_mission(self):
        self.mission_selected = False
        self.mission_started = False
        self.reward_clicked = False

    @staticmethod
    def read_reference(data):
        picture = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if picture is None:
            raise RuntimeError("A screen reference is unreadable. Reconfigure the mission.")
        return cv2.cvtColor(picture, cv2.COLOR_BGR2RGB)

    def guard(self):
        if escape_requested():
            raise MenuRequested("Escape pressed.")
        if u.GetForegroundWindow() != self.hwnd or bounds(self.hwnd) != self.box:
            raise RuntimeError("Game lost focus, moved, or changed size.")

    def frame(self):
        self.guard()
        return normalize(ImageGrab.grab(bbox=self.box, all_screens=True))

    def grade_button_match(self, frame):
        left, top, right, bottom = 460, 180, 930, 510
        area = frame[top:bottom, left:right]
        hsv = cv2.cvtColor(area, cv2.COLOR_RGB2HSV)
        lower, upper = {"A": (90, 130), "B": (35, 90), "C": (130, 170)}[self.settings["grade"]]
        colored = ((hsv[:, :, 0] >= lower) & (hsv[:, :, 0] <= upper)
                   & (hsv[:, :, 1] >= 90) & (hsv[:, :, 2] >= 70)).astype(np.float32)
        coverage = cv2.boxFilter(colored, -1, (280, 48), normalize=True)
        template = self.refs["Grade button"][0]
        height, width = template.shape[:2]
        scores = cv2.matchTemplate(area, template, cv2.TM_CCOEFF_NORMED)
        valid = coverage[height // 2:height // 2 + scores.shape[0],
                         width // 2:width // 2 + scores.shape[1]] >= 0.08
        scores[~valid] = -1
        _, score, _, (x, y) = cv2.minMaxLoc(scores)
        return score, (left + x + width // 2, top + y + height // 2)

    def match(self, frame, name):
        if name == "Grade button":
            return self.grade_button_match(frame)
        x, y = self.markers[name]
        best = (-1.0, (x, y))
        for template in self.refs[name]:
            height, width = template.shape[:2]
            left, top = x - width // 2, y - height // 2
            if name == "Level Up":
                left, top, right, bottom = 280, 82, 680, 245
            elif name == "Level Up checkmark":
                left, top, right, bottom = 770, 294, 945, 490
            else:
                margin = 18 if name == "Grade button" else 12
                right, bottom = left + width + margin, top + height + margin
                left, top = left - margin, top - margin
            area = frame[top:bottom, left:right]
            if name == "Page counter":
                # Compare digit outlines so the shared pale background cannot
                # make different counters appear to match.
                area = (cv2.cvtColor(area, cv2.COLOR_RGB2GRAY) < 95).astype(np.uint8) * 255
                template = (cv2.cvtColor(template, cv2.COLOR_RGB2GRAY) < 95).astype(np.uint8) * 255
                points = cv2.findNonZero(template)
                if points is None:
                    continue
                tx, ty, tw, th = cv2.boundingRect(points)
                template = template[ty:ty + th, tx:tx + tw]
            scores = cv2.matchTemplate(area, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, (dx, dy) = cv2.minMaxLoc(scores)
            if score > best[0]:
                best = score, (left + dx + width // 2, top + dy + height // 2)
        return best

    def score(self, frame, name):
        return self.match(frame, name)[0]

    def sees(self, frame, name):
        return self.score(frame, name) >= self.threshold(name)

    @staticmethod
    def threshold(name):
        return {"Claim": 0.71, "Grade button": 0.66, "Page counter": 0.76,
                "Mission list": 0.88, "Mission row": 0.86, "Next page": 0.60}.get(name, 0.80)

    def wait_for(self, name, seconds=12):
        end = time.monotonic() + seconds
        best = 0
        while time.monotonic() < end:
            frame = self.frame()
            score = self.score(frame, name)
            best = max(best, score)
            if score >= self.threshold(name):
                return frame
            time.sleep(0.10)
        raise RuntimeError(f"Could not find {name} (best match {best:.2f}).")

    def click(self, name, point=None):
        self.guard()
        x, y = point if point is not None else CLICK_POINTS[name]
        x = self.box[0] + round(x * self.width / WIDTH)
        y = self.box[1] + round(y * self.height / HEIGHT)
        target = u.WindowFromPoint(wt.POINT(x, y))
        if not target or u.GetAncestor(target, 2) != self.hwnd:
            raise RuntimeError(f"Another window is covering {name}.")
        if not u.SetCursorPos(x, y):
            raise RuntimeError("Could not move the mouse.")
        combat_action = name == "Attack" or name.startswith("Skill ")
        if combat_action:
            time.sleep(0.12)
        self.guard()
        if u.GetAncestor(u.WindowFromPoint(wt.POINT(x, y)), 2) != self.hwnd:
            raise RuntimeError(f"The click target for {name} changed.")
        u.mouse_event(0x0002, 0, 0, 0, 0)
        try:
            time.sleep(0.14 if combat_action else 0.04)
        finally:
            u.mouse_event(0x0004, 0, 0, 0, 0)
        if combat_action:
            time.sleep(0.22)
            print(f"{name} click sent at screen position ({x}, {y}).", flush=True)
        else:
            print(name, flush=True)

    def select_mission(self):
        frame = self.frame()
        opened_first_page = False
        if self.mission_selected and self.sees(frame, "Mission list") and self.sees(frame, "Start mission"):
            self.start_mission()
            return
        if not self.sees(frame, "Mission list"):
            if not self.sees(frame, "Grade button"):
                self.wait_for("Battle")
                self.click("Battle")
            frame = self.wait_for("Grade button")
            self.click(f"Grade {self.settings['grade']}", self.match(frame, "Grade button")[1])
            frame = self.wait_for("Mission list")
            opened_first_page = True

        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if not self.sees(frame, "Mission list"):
                raise RuntimeError("Lost the configured mission list.")
            first_page_requested = int(self.settings["page"].split("/")[0]) == 3
            target_page = self.sees(frame, "Page counter") or (first_page_requested and opened_first_page)
            row_present = self.sees(frame, "Mission row")
            if target_page and not row_present and first_page_requested:
                frame = self.wait_for("Mission row")
                if not self.sees(frame, "Mission list"):
                    raise RuntimeError("The mission list changed while checking the target row.")
                row_present = True
            if target_page and row_present:
                self.click(self.settings["name"], self.match(frame, "Mission row")[1])
                self.mission_selected = True
                self.start_mission()
                return
            if first_page_requested:
                raise RuntimeError(
                    "3/X means the first mission page. Return to the village and press F8 "
                    "so the macro can reopen the grade at the first page."
                )
            arrow_score, arrow_point = self.match(frame, "Next page")
            if arrow_score < self.threshold("Next page"):
                # Some pages render the same control without its highlight.
                # Its location is fixed within the verified mission list.
                arrow_point = self.markers["Next page"]
            left, top, right, bottom = CALIBRATION_BOXES["Page counter"]
            previous = frame[top:bottom, left:right]
            self.click("Next page", arrow_point)
            opened_first_page = False
            transition_deadline = time.monotonic() + 4
            while time.monotonic() < transition_deadline:
                frame = self.frame()
                counter = frame[top:bottom, left:right]
                if self.sees(frame, "Mission list") and cv2.absdiff(previous, counter).mean() > 2:
                    time.sleep(0.25)
                    frame = self.wait_for("Mission list", seconds=2)
                    break
                time.sleep(0.12)
            else:
                raise RuntimeError(
                    f"The right arrow did not advance the page while looking for "
                    f"{self.settings['name']} on {self.settings['page']}. "
                    "If you are past the target page, return to the village and press F8."
                )
        raise RuntimeError(
            f"Could not find {self.settings['name']} on {self.settings['page']}. "
            "Start from the village, or reconfigure the mission if its row changed."
        )

    def start_mission(self):
        self.wait_for("Start mission")
        self.click("Start mission")
        self.mission_started = True

    def play_mission(self, current_only=False):
        frame = self.frame()
        if self.sees(frame, "Battle"):
            if self.reward_clicked:
                print("Reward claimed. Back at the main menu.", flush=True)
                return
            if current_only:
                raise RuntimeError("Use F8 from the village. F9 is for an active mission.")
            self.reset_mission()
        elif self.sees(frame, "Level Up"):
            self.claim_reward(frame, already_claimed=True)
            return
        elif self.sees(frame, "Mission Success"):
            self.claim_reward(frame)
            return
        elif self.reward_clicked:
            self.claim_reward(frame, already_claimed=True)
            return
        elif current_only:
            if not (self.attack_control(frame)[1] is not None and self.sees(frame, "Turn timer")):
                raise RuntimeError("Press F9 on your turn, Mission Success, or Level Up.")
            self.finish_mission()
            return

        if not self.mission_started:
            self.select_mission()
        self.finish_mission()

    def attack_control(self, frame):
        attack_score, attack_point = self.match(frame, "Attack")
        if attack_score >= self.threshold("Attack"):
            return attack_score, attack_point

        # Some turns render the Attack icon differently. Confirm its position
        # against the neighboring Dodge button before accepting a weaker match.
        dodge_score, (x, y) = self.match(frame, "Dodge")
        if dodge_score >= 0.82 and (attack_score >= 0.50 or self.sees(frame, "Attack label")):
            return attack_score, (x - 52, y - 1)
        return attack_score, None

    def claim_reward(self, frame, already_claimed=False):
        if already_claimed:
            self.reward_clicked = True
        deadline = time.monotonic() + 15
        last_click = None
        attempts = 0
        success_closed = already_claimed
        level_up_clicked = False
        claim_score = 0.0
        while time.monotonic() < deadline:
            if self.sees(frame, "Battle") and not self.sees(frame, "Mission Success"):
                if attempts or already_claimed:
                    print("Reward claimed. Back at the main menu.", flush=True)
                    return
                raise RuntimeError("The reward screen closed before Claim was clicked.")
            if self.sees(frame, "Mission Success"):
                claim_score, point = max(
                    (self.match(frame, name) for name in ("Claim", "Claim plain")),
                    key=lambda match: match[0],
                )
                retry = last_click is not None and time.monotonic() - last_click >= 2.0
                if claim_score >= self.threshold("Claim") and not success_closed and attempts < 2:
                    if last_click is None or retry:
                        self.click("Claim", point)
                        self.reward_clicked = True
                        attempts += 1
                        last_click = time.monotonic()
            elif attempts or already_claimed:
                success_closed = True
                if not level_up_clicked and self.sees(frame, "Level Up"):
                    score, point = self.match(frame, "Level Up checkmark")
                    if score >= self.threshold("Level Up checkmark"):
                        self.click("Level Up checkmark", point)
                        level_up_clicked = True
            time.sleep(0.12)
            frame = self.frame()
        if attempts or already_claimed:
            raise RuntimeError("The reward sequence did not return to Battle.")
        raise RuntimeError(f"Mission Success appeared, but Claim was not recognized ({claim_score:.2f}).")

    def combat_action(self, frame, attack_point):
        if self.settings["mode"] == "attack":
            return "Attack", attack_point
        for number, (x, y) in enumerate(SKILL_POINTS, 1):
            icon = frame[y - 13:y + 13, x - 13:x + 13].astype(np.int16)
            colorful = (np.ptp(icon, axis=2) >= 35).mean()
            if colorful >= 0.18:
                return f"Skill {number}", (x, y)
        return "Attack", attack_point

    def finish_mission(self):
        deadline = time.monotonic() + 150
        last_progress = time.monotonic()
        last_attack = None
        inactive_frames = 0
        retries = 0
        actions = 0
        dialogs = 0
        attack_score = timer_score = 0.0
        while time.monotonic() < min(deadline, last_progress + 25):
            frame = self.frame()
            if self.sees(frame, "Mission Success"):
                self.claim_reward(frame)
                return
            if self.sees(frame, "Continue"):
                if dialogs == 12:
                    raise RuntimeError("Dialogue did not finish.")
                self.click("Continue")
                dialogs += 1
                last_progress = time.monotonic()
                time.sleep(0.65)
                continue

            attack_score, point = self.attack_control(frame)
            timer_score = self.score(frame, "Turn timer")
            attack_visible = point is not None
            timer_visible = timer_score >= self.threshold("Turn timer")
            now = time.monotonic()
            if attack_visible and timer_visible:
                inactive_frames = 0
                retry = last_attack is not None and now - last_attack >= 2.5 and retries < 2
                if last_attack is None or retry:
                    action, action_point = self.combat_action(frame, point)
                    if retry:
                        retries += 1
                        print(f"Turn controls still visible. Rechecking skills ({retries}/2).", flush=True)
                    self.click(action, action_point)
                    # Move away from the combat controls to clear hover effects.
                    self.guard()
                    u.SetCursorPos(self.box[0] + self.width // 2, self.box[3] - 12)
                    last_attack = time.monotonic()
                    actions += 1
                    last_progress = last_attack
            elif last_attack is not None:
                inactive_frames += 1
                if (not attack_visible and not timer_visible) or inactive_frames >= 2:
                    last_attack = None
                    retries = 0
            time.sleep(0.08)

        raise RuntimeError(
            f"Combat timed out after {actions} combat click(s). "
            f"Last screen matches: Attack {attack_score:.2f}, turn timer {timer_score:.2f}."
        )


def calibration_boxes(row):
    y = ROW_CENTERS[row - 1]
    return {**CALIBRATION_BOXES, "Mission row": (516, y - 13, 806, y + 13)}


def game_hotkey(keys, cancel_with_escape=True):
    if cancel_with_escape:
        print("Press Escape to cancel.", flush=True)
    while any(pressed(key) for key in (*keys, 0x1B)):
        time.sleep(0.08)
    while not escape_requested():
        hwnd = u.GetForegroundWindow()
        if title(hwnd) == "Ninja Kaizen":
            for key in keys:
                if pressed(key):
                    return hwnd, key
        time.sleep(0.08)
    raise MenuRequested("Escape pressed.")


def choose(prompt, options, labels=None):
    """Arrow-key menu: Up/Down to move, Enter to pick, or press an option's key directly."""
    labels = labels or {}
    index = 0
    print(prompt)

    def draw(first=False):
        if not first:
            sys.stdout.write(f"\x1b[{len(options)}A")
        for i, option in enumerate(options):
            marker = ">" if i == index else " "
            text = f"{option} - {labels[option]}" if option in labels else option
            line = f"  {marker} {text}"
            sys.stdout.write(f"\x1b[2K\x1b[7m{line}\x1b[0m\n" if i == index else f"\x1b[2K{line}\n")
        sys.stdout.flush()

    os.system("")  # enable ANSI escape handling in the Windows console
    draw(first=True)
    while True:
        key = msvcrt.getwch()
        if key in ("\x00", "\xe0"):
            arrow = msvcrt.getwch()
            if arrow == "H":
                index = (index - 1) % len(options)
            elif arrow == "P":
                index = (index + 1) % len(options)
            draw()
        elif key == "\r":
            return options[index]
        elif key == "\x03":
            raise KeyboardInterrupt
        elif key.upper() in options:
            index = options.index(key.upper())
            draw()
            return options[index]


def setup():
    previous = None
    if SETTINGS.is_file():
        try:
            previous = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            print("Saved setup could not be read. Configure the mission again.")
    if previous:
        print(f"Saved mission: Grade {previous['grade']}, {previous['page']}, {previous['name']}")
        choice = input("Enter to reuse, S to set up a mission, or Q to quit: ").strip().upper()
        if choice == "Q":
            return None
        if not choice:
            return previous
        if choice != "S":
            raise RuntimeError("Press Enter, S, or Q.")

    grade = choose("Mission grade:", ["A", "B", "C", "Q"], {"Q": "Quit"})
    if grade == "Q":
        return None
    presets = [mission for mission in MISSIONS if mission[0] == grade]
    names = [mission[1] for mission in presets] + ["Other", "Q"]
    picked = choose("Mission name:", names, {"Other": "type it in", "Q": "Quit"})
    if picked == "Q":
        return None
    if picked != "Other":
        _, name, page, row = next(mission for mission in presets if mission[1] == picked)
    else:
        name = input("Mission name: ").strip()
        page = input("Page as displayed, for example 6/10: ").strip()
        numbers = page.split("/")
        if not name or len(numbers) != 2 or not all(part.isascii() and part.isdigit() and len(part) <= 4 for part in numbers):
            raise RuntimeError("Enter a mission name and a page in the form 6/10.")
        if not 1 <= int(numbers[0]) <= int(numbers[1]):
            raise RuntimeError("The page counter is out of range.")
        row = input("Mission row [1 top, 2 middle, 3 bottom]: ").strip()
        if row not in ("1", "2", "3"):
            raise RuntimeError("Choose row 1, 2, or 3.")

    print(f"Open Grade {grade} at {page} with {name} in row {row}.")
    print("Keep the game fully visible, move the cursor away from the mission list, and press F7 in the game.")
    hwnd, _ = game_hotkey((0x76,))
    frame = Farm(hwnd).frame()
    refs = {}
    for key, (left, top, right, bottom) in calibration_boxes(int(row)).items():
        patch = frame[top:bottom, left:right]
        if np.std(patch.astype(np.float32).mean(axis=2)) < 10:
            raise RuntimeError("The mission list could not be captured. Open it and try setup again.")
        ok, png = cv2.imencode(".png", cv2.cvtColor(patch, cv2.COLOR_RGB2BGR))
        if not ok:
            raise RuntimeError("Could not save the mission reference.")
        refs[key] = base64.b64encode(png).decode("ascii")
    print("Mission screen captured. Return to this console to choose combat and run count.")
    return {"grade": grade, "name": name, "page": page, "row": int(row), "refs": refs, "mode": "skills"}


def main():
    print("Ninja Kaizen Macro v3")
    while True:
        try:
            settings = setup()
            if settings is None:
                return
            configure_batch(settings)
        except (RuntimeError, ValueError, KeyError) as error:
            print(f"Setup incomplete. {error}")
        print()


def configure_batch(settings):
    default = "1" if settings["mode"] == "attack" else "2"
    mode = input(f"Combat [1 Normal Attack, 2 Skills then Attack, Enter = {default}]: ").strip() or default
    if mode not in ("1", "2"):
        raise RuntimeError("Choose combat mode 1 or 2.")
    settings["mode"] = "attack" if mode == "1" else "skills"
    runs = input("Number of missions [1, 0 = continuous]: ").strip() or "1"
    if not runs.isascii() or not runs.isdigit() or len(runs) > 3 or not 0 <= int(runs) <= 100:
        raise RuntimeError("Choose 0 for continuous mode or 1 to 100 runs.")
    runs = int(runs)
    pending = SETTINGS.with_suffix(".tmp")
    pending.write_text(json.dumps(settings), encoding="utf-8")
    pending.replace(SETTINGS)

    print("F8 starts or resumes. Escape returns to mission setup. Switching windows pauses.")
    print("F9 finishes the current mission, then returns to setup. Close this console to quit.")
    run_batch(settings, runs)


def run_batch(settings, runs):
    escape_request.clear()
    stop = threading.Event()
    watcher = threading.Thread(target=watch_escape, args=(stop,), daemon=True)
    watcher.start()
    try:
        execute_batch(settings, runs)
    finally:
        stop.set()
        watcher.join()
        escape_request.clear()


def execute_batch(settings, runs):
    completed = 0
    farm = None
    while runs == 0 or completed < runs:
        try:
            hwnd, key = game_hotkey((0x77, 0x78), cancel_with_escape=False)
            if farm is None:
                farm = Farm(hwnd, settings)
            else:
                farm.attach(hwnd)
            if key == 0x78:
                counted_mission = farm.mission_started or farm.reward_clicked
                farm.play_mission(current_only=True)
                farm.reset_mission()
                completed += int(counted_mission)
                print("Finished the current mission. Returning to mission setup.", flush=True)
                return
            while runs == 0 or completed < runs:
                if escape_requested():
                    raise MenuRequested("Escape pressed.")
                run = completed + 1
                label = f"Run {run}" if runs == 0 else f"Run {run} of {runs}"
                print(label, flush=True)
                farm.play_mission()
                completed += 1
                farm.reset_mission()
        except MenuRequested:
            print(f"Returning to mission setup. Completed missions: {completed}.", flush=True)
            return
        except (RuntimeError, OSError) as error:
            print(f"Paused. {error} Completed missions: {completed}. Press F8 in the game to resume.", flush=True)
    print(f"Finished {completed} run(s).")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (RuntimeError, OSError, KeyError, ValueError, EOFError) as error:
        print(f"Stopped. {error}")
        raise SystemExit(1)



