"""Pure state and arbitration for Light Multiplexer."""
from copy import deepcopy

PULSE = "Pulse"
NORMAL = "off"

def signal_key(index):
    return "signal" if index == 1 else f"signal_{index}"

def normalize(saved, count, source=None):
    source = source or {}
    states = {"base": {"on": source.get("on", False), "brightness": source.get("brightness", 255),
                       "color_temp_kelvin": source.get("color_temp_kelvin", 3000)}}
    for index in range(1, count + 1):
        states[signal_key(index)] = {"on": False, "brightness": 128, "hs_color": [0, 100], "effect": NORMAL}
    for key, value in (saved or {}).items():
        if key in states:
            states[key].update({k: v for k, v in value.items() if k in states[key]})
    for key, value in states.items():
        if key != "base":
            if value["effect"] not in (NORMAL, PULSE):
                value["effect"] = NORMAL
    return states

class Model:
    def __init__(self, states):
        self.states = states
        self.queue = []
        self.new_queue = []
        self.current = None
        self.phase = "idle"
        self.sync()

    def sync(self):
        active = [key for key, value in self.states.items()
                  if key != "base" and value["on"] and value["effect"] == PULSE]
        self.queue = [key for key in self.queue if key in active]
        self.new_queue = [key for key in self.new_queue if key in active]
        for key in active:
            if key != self.current and key not in self.queue and key not in self.new_queue:
                self.new_queue.append(key)
        if self.current is not None and self.current not in active:
            self.current = None
            self.phase = "pause"
            return True
        return False

    def advance(self):
        if self.phase == "show":
            if self.current:
                self.queue.append(self.current)
            self.current = None
            self.phase = "pause"
        elif self.new_queue or self.queue:
            queue = self.new_queue if self.new_queue else self.queue
            self.current = queue.pop(0)
            self.phase = "show"
        else:
            self.current = None
            self.phase = "idle"

    def output(self):
        key = self.current
        if key is None:
            candidates = [key for key, value in self.states.items()
                          if key != "base" and value["on"] and value["effect"] != PULSE]
            key = candidates[-1] if candidates else "base"
        selected = deepcopy(self.states[key])
        if not selected["on"]:
            return {"on": False}
        if key != "base" and self.states["base"]["on"]:
            selected["brightness"] = max(selected["brightness"], self.states["base"]["brightness"])
        selected.pop("effect", None)
        return selected
