"""A made-up library for showing Homecoming without anyone's real data: seven years of one invented person's life,
Riley Park, written the way the connectors write a real one (normalized/*.jsonl, manifest.json, identity.json), then
indexed. The people, places and trips follow the welcome tour's (src/renderer/examples.ts): college friends and
roommates in San Francisco, Maya from climbing, a move to Chicago together last August and a new job there, trips to
Tokyo and Kyoto, Lisbon and Porto, Mexico City and Oaxaca. Every name, address and number is invented (phone numbers
are 555 ones, email is example.com or a service's own). Dates are relative to today.

    python3 desktop/scripts/demo_library.py --corpus DIR [--photos DIR] [--home DIR]

--photos: a folder of pictures (.jpg/.png) to cut the library's photos from; a file's name says where it was taken
(sf_, chicago_, tokyo_, kyoto_, lisbon_, porto_, nyc_; anything else is a picture from home). Without it, photos are
soft drawn gradients. --home: a made-up home folder to fill with what the app looks for on a Mac (an iPhone backup,
the settings that keep history), so the setup checks pass.
"""

import argparse
import collections
import datetime as dt
import json
import math
import os
import plistlib
import random
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[2]
UTC = dt.timezone.utc

ap = argparse.ArgumentParser()
ap.add_argument("--corpus", required=True)
ap.add_argument("--photos")
ap.add_argument("--home")
ap.add_argument("--seed", type=int, default=20261015)
ARGS = ap.parse_args()
CORPUS = Path(ARGS.corpus).resolve()
os.environ["CORPUS_DIR"] = str(CORPUS)
sys.path.insert(0, str(REPO / "connectors"))
from common import Writer  # noqa: E402  (reads CORPUS_DIR on import)

_add = Writer.add


def _until_now(self, **rec):
    """Nothing from later today; the calendar alone looks ahead."""
    if self.source != "calendar" and str(rec.get("ts") or "") > NOW_ISO:
        return
    _add(self, **rec)


Writer.add = _until_now

R = random.Random(ARGS.seed)
NOW = dt.datetime.now(UTC).replace(microsecond=0)
NOW_ISO = NOW.isoformat().replace("+00:00", "Z")
TODAY = NOW.astimezone(ZoneInfo("America/Chicago")).date()
Y = TODAY.year
START = dt.date(Y - 6, 1, 4)


def y(back, md):
    return dt.date(Y - back, int(md[:2]), int(md[3:]))


ME = {"name": "Riley Park", "first": "Riley", "email": "riley.park@example.com", "work": "riley@lumenlabs.example",
      "old_work": "riley@fernwood.example", "username": "rileyp", "phone": "+1 415 555 0142"}

# ---------------------------------------------------------------- places

CITY = {  # lat, lon, region, country, time zone
    "San Francisco": (37.7694, -122.4294, "California", "United States", "America/Los_Angeles"),
    "Chicago": (41.9145, -87.6554, "Illinois", "United States", "America/Chicago"),
    "New York": (40.7194, -73.9976, "New York", "United States", "America/New_York"),
    "Seattle": (47.6131, -122.3384, "Washington", "United States", "America/Los_Angeles"),
    "Denver": (39.7392, -104.9903, "Colorado", "United States", "America/Denver"),
    "Austin": (30.2672, -97.7431, "Texas", "United States", "America/Chicago"),
    "Lisbon": (38.7139, -9.1394, "Lisbon", "Portugal", "Europe/Lisbon"),
    "Porto": (41.1496, -8.6110, "Porto", "Portugal", "Europe/Lisbon"),
    "Tokyo": (35.6595, 139.7005, "Tokyo", "Japan", "Asia/Tokyo"),
    "Kyoto": (35.0116, 135.7681, "Kyoto", "Japan", "Asia/Tokyo"),
    "Mexico City": (19.4204, -99.1607, "Mexico City", "Mexico", "America/Mexico_City"),
    "Oaxaca": (17.0654, -96.7236, "Oaxaca", "Mexico", "America/Mexico_City"),
    "London": (51.5145, -0.1300, "England", "United Kingdom", "Europe/London"),
    "Paris": (48.8606, 2.3376, "Île-de-France", "France", "Europe/Paris"),
    "Vancouver": (49.2827, -123.1207, "British Columbia", "Canada", "America/Vancouver"),
}
HOOD = {"San Francisco": ["Mission District", "Dolores Park", "Ocean Beach", "Golden Gate Park", "the Presidio", "Bernal Heights", "North Beach"],
        "Chicago": ["Wicker Park", "Logan Square", "the Lakefront Trail", "Millennium Park", "Humboldt Park", "the West Loop", "Montrose Beach"]}
ROUTE = [  # where Riley was, from the day they arrived (the welcome tour's route)
    ("San Francisco", START), ("Seattle", y(6, "07-02")), ("San Francisco", y(6, "07-09")), ("Vancouver", y(5, "05-20")),
    ("San Francisco", y(5, "05-27")), ("London", y(4, "06-03")), ("Paris", y(4, "06-09")), ("San Francisco", y(4, "06-16")),
    ("Austin", y(3, "03-10")), ("San Francisco", y(3, "03-14")), ("Mexico City", y(2, "11-18")), ("Oaxaca", y(2, "11-22")),
    ("San Francisco", y(2, "11-29")), ("Tokyo", y(1, "03-28")), ("Kyoto", y(1, "04-02")), ("San Francisco", y(1, "04-08")),
    ("Lisbon", y(1, "05-16")), ("Porto", y(1, "05-21")), ("San Francisco", y(1, "05-26")), ("Chicago", y(1, "08-01")),
    ("New York", y(1, "12-20")), ("Chicago", y(1, "12-28")), ("Denver", y(0, "02-14")), ("Chicago", y(0, "02-18")),
]
MOVE = y(1, "08-01")  # San Francisco to Chicago, with Maya
NEW_JOB = y(1, "09-08")  # Lumen Labs, Chicago; Fernwood, San Francisco, before
RACE = TODAY + dt.timedelta(days=42)  # the half marathon, six weeks out


def where(d):
    city = ROUTE[0][0]
    for c, since in ROUTE:
        if since <= d:
            city = c
    return city


def home_city(d):
    return "Chicago" if d >= MOVE else "San Francisco"


def away(d):
    return where(d) not in ("San Francisco", "Chicago")


def at(d, hour, minute=0, city=None):
    """A local time on day d (where Riley was) as UTC ISO."""
    tz = ZoneInfo(CITY[city or where(d)][4])
    h = int(hour) % 24
    extra = int(hour) // 24
    t = dt.datetime(d.year, d.month, d.day, h, int(minute), R.randint(0, 59), tzinfo=tz) + dt.timedelta(days=extra)
    return t.astimezone(UTC).isoformat().replace("+00:00", "Z")


def days(a, b):
    while a <= b:
        yield a
        a += dt.timedelta(days=1)


def pick(xs):
    return xs[R.randrange(len(xs))]


def fill(s):
    return s.format(**{k: pick(v) for k, v in SLOTS.items() if "{" + k + "}" in s})


# ---------------------------------------------------------------- people

# [messages each year (oldest first, scaled down below), the month they first talked, other apps' share, calls a year]
CAST = {
    "Maya Chen": ([0, 0, 0, 640, 3480, 4212, 1290], 5, {"instagram": 0.12}, 40),
    "Jordan Reyes": ([310, 980, 2860, 2410, 1890, 2180, 1240], 3, {"instagram": 0.2}, 8),
    "Priya Patel": ([2240, 2910, 1780, 2620, 1210, 980, 820], 1, {"instagram": 0.15}, 7),
    "Mom": ([1180, 1320, 1240, 1390, 1460, 1730, 1210], 1, {"phone_whatsapp": 0.35}, 26),
    "Sam Okafor": ([3120, 2350, 940, 610, 480, 520, 290], 1, {"messenger": 0.3}, 4),
    "Ana Souza": ([860, 790, 1020, 880, 940, 1110, 760], 1, {"phone_whatsapp": 0.4}, 6),
    "Leo Martins": ([0, 0, 0, 380, 1640, 1290, 410], 9, {}, 2),
    "Ruby Walsh": ([0, 0, 0, 0, 0, 640, 1380], 9, {"instagram": 0.3}, 2),
    "Grace Kim": ([0, 0, 0, 290, 1120, 860, 690], 5, {"instagram": 0.25}, 1),
    "Dad": ([420, 380, 460, 510, 470, 640, 390], 1, {"phone_whatsapp": 0.3}, 12),
    "Kenji Watanabe": ([140, 210, 180, 260, 320, 1180, 240], 2, {"phone_whatsapp": 0.5}, 2),
    "Theo Laurent": ([0, 0, 0, 0, 0, 0, 980], 1, {}, 2),
    "Zoe Fischer": ([0, 0, 120, 410, 620, 540, 380], 10, {}, 1),
    "Noah Bennett": ([0, 0, 0, 180, 540, 610, 470], 6, {"instagram": 0.2}, 1),
    "Omar Haddad": ([510, 460, 380, 300, 240, 160, 90], 1, {"phone_whatsapp": 0.6, "messenger": 0.2}, 1),
    "Ines Duarte": ([0, 0, 0, 0, 0, 420, 210], 5, {"phone_whatsapp": 0.5}, 1),
    "Lucia Romero": ([0, 0, 0, 0, 380, 290, 120], 11, {"phone_whatsapp": 0.7}, 1),
    "Kai Nakamura": ([0, 0, 0, 0, 310, 280, 150], 2, {"instagram": 0.4}, 0),
    "Hana Sato": ([0, 0, 0, 0, 0, 260, 140], 4, {"instagram": 0.5}, 0),
    "Marcus Lee": ([0, 0, 0, 120, 260, 310, 220], 7, {}, 1),
}
OTHERS = ["Ethan Brooks", "Aisha Bello", "Diego Alvarez", "Chloe Martin", "Felix Wagner", "Nadia Rahman", "Iris Novak", "Luca Carter",
          "Elena Petrova", "Sofia Rossi", "Jamal Wright", "Mei Lin", "Oscar Silva", "Lena Hoffmann", "Tom Hughes", "Ravi Kumar",
          "Clara Jensen", "Max Turner", "Julia Costa"]
for n in OTHERS:
    a = R.randint(0, 6)
    b = min(6, a + R.randint(1, 5))
    CAST[n] = ([R.randint(20, 260) if a <= i <= b else 0 for i in range(7)], R.randint(1, 12),
               {"instagram": 0.5} if R.random() < 0.3 else {}, R.randint(0, 2))
SCALE = 0.32
FIRST = {n: n.split()[0] for n in CAST}
PHONE = {n: f"+1 {R.choice(['312', '415', '773', '510', '628'])} 555 {R.randint(100, 199):04d}" for n in CAST}
EMAIL = {n: f"{n.split()[0].lower()}.{n.split()[-1].lower()}@example.com" if " " in n else f"{n.lower()}.park@example.com" for n in CAST}

SLOTS = {
    "food": ["ramen", "tacos", "pho", "dumplings", "pizza", "thai", "burritos", "sushi", "dim sum", "falafel", "khachapuri", "pupusas"],
    "day": ["saturday", "sunday", "friday", "tomorrow", "tonight", "thursday"],
    "time": ["7", "7:30", "8", "6:30", "noon", "11", "1"],
    "show": ["Severance", "The Bear", "Shogun", "Slow Horses", "Hacks", "The Rehearsal", "Andor"],
    "book": ["Tomorrow, and Tomorrow, and Tomorrow", "Piranesi", "The Overstory", "Project Hail Mary", "Station Eleven"],
    "thing": ["the projector", "your blue jacket", "the camping stove", "the good knife", "that board game", "the ladder"],
    "drink": ["coffee", "a drink", "boba", "a beer", "matcha"],
    "artist": ["Phoebe Bridgers", "Bon Iver", "Japanese Breakfast", "Khruangbin", "Mitski", "Fred again..", "Big Thief"],
}
GENERIC = [
    [("a", "are you around {day}?"), ("b", "yes! what's up"), ("a", "{food}?"), ("b", "always. {time}?"), ("a", "perfect")],
    [("a", "did you finish {show}"), ("b", "two episodes left, no spoilers"), ("a", "my lips are sealed 🤐")],
    [("a", "happy friday!!"), ("b", "happy friday 🎉 any plans?"), ("a", "absolutely nothing and I can't wait")],
    [("a", "can I borrow {thing} this weekend?"), ("b", "of course, come grab it whenever"), ("a", "you're the best")],
    [("a", "just finished {book}"), ("b", "and??"), ("a", "loved it. you have to read it"), ("b", "adding it to the list")],
    [("a", "{drink} this week?"), ("b", "wednesday after work?"), ("a", "works for me"), ("b", "same spot as last time")],
    [("a", "running 10 min late sorry!!"), ("b", "no worries, grabbing a table")],
    [("a", "omg I just saw your post"), ("b", "haha it was a good day"), ("a", "so jealous")],
    [("a", "what are you up to"), ("b", "laundry and podcasts. thrilling"), ("a", "living the dream")],
    [("a", "have you listened to the new {artist} album"), ("b", "on repeat"), ("a", "track 4 though")],
    [("a", "thank you for last night, that was so fun"), ("b", "it really was! let's do it again soon")],
    [("a", "call later?"), ("b", "yes, after 8?"), ("a", "👍")],
    [("a", "this made me think of you"), ("b", "HAHA stop"), ("b", "that's exactly me")],
    [("a", "how was the weekend"), ("b", "so good, went hiking"), ("a", "where?"), ("b", "a trail outside the city, photos soon")],
    [("a", "are we still on for {day}"), ("b", "yes! I'll book it"), ("a", "amazing")],
    [("a", "I'm making {food} if you want to come by"), ("b", "on my way"), ("a", "bring nothing, just you")],
    [("a", "good luck today!!"), ("b", "thank you 🥹"), ("b", "it went well I think")],
    [("a", "ok I have a hot take"), ("b", "go"), ("a", "{food} is overrated"), ("b", "absolutely not"), ("b", "we're fighting")],
    [("a", "miss you!"), ("b", "miss you more. visit soon?"), ("a", "working on it")],
    [("a", "did you get home ok"), ("b", "yep! thanks for dinner")],
]
TOPICS = {
    "Maya Chen": [
        [("a", "climb tonight?"), ("b", "yes, 7:30?"), ("a", "see you there 🧗")],
        [("a", "grabbing groceries, want anything?"), ("b", "limes and the good bread"), ("a", "got it")],
        [("a", "leaving work now, climb or dinner?"), ("b", "climb then dinner"), ("a", "perfect plan")],
        [("a", "look at this dog outside the cafe"), ("b", "I need him"), ("b", "go pet him for me")],
        [("a", "the landlord finally fixed the radiator 🙌"), ("b", "a miracle"), ("a", "we can feel our toes again")],
        [("a", "I finally sent the overhang problem"), ("b", "LET'S GO"), ("b", "drinks on me")],
        [("a", "who's cooking tonight"), ("b", "you, I did tuesday"), ("a", "fair. {food} it is")],
    ],
    "Mom": [
        [("a", "How is the new job going?"), ("b", "Good! Busy week but good"), ("a", "Proud of you ❤️")],
        [("a", "Call me this weekend ❤️"), ("b", "Sunday morning?"), ("a", "Perfect")],
        [("a", "Did you get the package?"), ("b", "Yes!! the scarf is perfect, thank you"), ("a", "Stay warm out there")],
        [("a", "Are you eating vegetables"), ("b", "yes mom"), ("a", "Send a picture")],
        [("a", "Dad says hi"), ("b", "hi dad!!"), ("a", "He's watching the game again")],
        [("a", "Remember your dentist appointment"), ("b", "I know I know"), ("a", "Just checking 😊")],
    ],
    "Dad": [
        [("a", "Did you see the game"), ("b", "the last 5 minutes!!"), ("a", "Unbelievable")],
        [("a", "How's the car running"), ("b", "fine! don't worry"), ("a", "Check the tire pressure")],
        [("a", "Weather looks rough there"), ("b", "it's fine, I have the big coat"), ("a", "Good")],
    ],
    "Jordan Reyes": [
        [("a", "SF misses you"), ("b", "Chicago is stealing me, sorry"), ("a", "traitor")],
        [("a", "visiting in October, couch free?"), ("b", "always"), ("a", "bringing the good coffee")],
        [("a", "rent went up again"), ("b", "of course it did"), ("a", "I'm moving into a van")],
        [("a", "taco tuesday at the usual?"), ("b", "obviously")],
        [("a", "who ate my leftovers"), ("b", "...Sam"), ("a", "SAM")],
    ],
    "Priya Patel": [
        [("a", "sending the wedding photos tonight!"), ("b", "ahh can't wait"), ("b", "you looked so happy")],
        [("a", "are you still doing the half marathon?"), ("b", "6 weeks out, legs are confused"), ("a", "you've got this")],
        [("a", "remember the 3am library nights"), ("b", "how did we survive"), ("a", "vending machine dinners")],
        [("a", "long run this weekend?"), ("b", "10 miles saturday, send help"), ("a", "I'll bring snacks to mile 8")],
    ],
    "Sam Okafor": [
        [("a", "game night friday?"), ("b", "I'm in. bringing chips"), ("a", "the spicy ones")],
        [("a", "did you take my charger"), ("b", "...maybe"), ("a", "SAM")],
        [("a", "remember the dorm fire alarm at 4am"), ("b", "I still have nightmares")],
    ],
    "Leo Martins": [
        [("a", "can you look at my PR before standup?"), ("b", "on it"), ("b", "left two comments, looks good")],
        [("a", "lunch at the taco place?"), ("b", "12:15"), ("a", "👍")],
        [("a", "deploy is green 🎉"), ("b", "finally"), ("a", "beers?")],
        [("a", "Lisbon flights are cheap in May"), ("b", "don't tempt me"), ("a", "I'm tempting you"), ("b", "ok booking")],
    ],
    "Ruby Walsh": [
        [("a", "trivia tonight? we need a fourth"), ("b", "in. same bar as last time?"), ("a", "yes, 7:30")],
        [("a", "did you see the lake this morning?? unreal"), ("b", "biked along it at lunch, so good")],
        [("a", "the bakery on Milwaukee has cardamom buns today"), ("b", "omw")],
        [("a", "are you coming to the rooftop thing saturday"), ("b", "yes!! bringing Maya")],
    ],
    "Theo Laurent": [
        [("a", "climbing thursday?"), ("b", "yes, 7:30 at First Ascent"), ("a", "bring chalk, I'm out")],
        [("a", "that overhang problem is finally going down"), ("b", "send it 🧗")],
        [("a", "half marathon training check: how far this week"), ("b", "22 miles, my knees hate me")],
    ],
    "Grace Kim": [
        [("a", "new set at the gym is so good"), ("b", "going tomorrow after work"), ("a", "try the purple one")],
        [("a", "bouldering comp in June?"), ("b", "only if you do it with me")],
    ],
    "Kenji Watanabe": [
        [("a", "When are you landing in Tokyo?"), ("b", "the 28th, around 3pm"), ("a", "I'll meet you at Shibuya")],
        [("a", "You have to try the ramen place near my office"), ("b", "adding it to the list"), ("a", "Trust me")],
        [("a", "The cherry blossoms are early this year 🌸"), ("b", "perfect timing!!")],
    ],
    "Ana Souza": [
        [("a", "saudades!"), ("b", "miss you too!! call soon?"), ("a", "sunday?")],
        [("a", "I'm in SF next month for work"), ("b", "you're staying with us, no arguments")],
    ],
    "Lucia Romero": [
        [("a", "Oaxaca is calling you"), ("b", "I booked it!! november"), ("a", "Te voy a llevar a comer tlayudas")],
        [("a", "How was the flight?"), ("b", "long but worth it"), ("a", "Mezcal tonight")],
    ],
    "Ines Duarte": [
        [("a", "When you're in Lisbon, go to the miradouro at sunset"), ("b", "noted!!"), ("a", "And pastéis de nata, warm")],
        [("a", "Porto or Lisbon, which did you like more"), ("b", "impossible question"), ("a", "Correct answer")],
    ],
    "Marcus Lee": [
        [("a", "1:1 moved to 2pm, ok?"), ("b", "works"), ("a", "thanks")],
        [("a", "great demo today"), ("b", "thank you! team effort"), ("a", "let's write it up for the all-hands")],
    ],
    "Omar Haddad": [
        [("a", "brother! how's life"), ("b", "good! busy. you?"), ("a", "same. we need a call")],
    ],
}
# Moments, a few days each: what the messages around them are about. (start, days, people, exchanges)
EPISODES = [
    (y(1, "03-10"), 18, ["Kenji Watanabe", "Jordan Reyes"], [[("a", "Tokyo in 2 weeks!!"), ("b", "I made a list of 40 restaurants"), ("a", "we'll need 40 days")],
                                                         [("a", "JR pass or no?"), ("b", "yes for Kyoto"), ("a", "booked")],
                                                         [("a", "landed!!"), ("b", "welcome to Tokyo 🗼"), ("a", "jet lag is real")]]),
    (y(1, "03-28"), 11, ["Jordan Reyes", "Mom"], [[("a", "the train is so quiet here"), ("b", "send pictures!!")],
                                                  [("a", "Fushimi Inari at 7am, nobody there"), ("b", "magical")],
                                                  [("a", "I've had ramen 6 times"), ("b", "only 6?")]]),
    (y(1, "05-01"), 30, ["Maya Chen", "Leo Martins", "Ines Duarte"], [[("a", "Lisbon itinerary v3 in the doc"), ("b", "v3?? we haven't left"), ("a", "I'm thorough")],
                                                                       [("a", "pastel de nata count: 4"), ("b", "rookie numbers")],
                                                                       [("a", "the tram up to the castle was packed"), ("b", "walk next time, it's prettier")],
                                                                       [("a", "Porto tomorrow, train at 9"), ("b", "I'll get the tickets")]]),
    (y(1, "06-20"), 45, ["Maya Chen", "Mom", "Jordan Reyes", "Priya Patel"], [[("a", "we signed the Chicago lease!!"), ("b", "AHHH it's real"), ("a", "Wicker Park, 2 bedrooms, a radiator that clanks")],
                                                                              [("a", "boxes everywhere"), ("b", "how many are books"), ("a", "don't ask")],
                                                                              [("a", "first night in Chicago 🏙️"), ("b", "how does it feel"), ("a", "like the start of something")],
                                                                              [("a", "we're really leaving SF"), ("b", "I'm going to cry at the airport")]]),
    (y(1, "08-15"), 30, ["Mom", "Dad", "Priya Patel", "Maya Chen"], [[("a", "I got the job at Lumen Labs!!"), ("b", "!!!!! so proud of you"), ("a", "start in September")],
                                                                     [("a", "first day done"), ("b", "how was it??"), ("a", "everyone is so nice, I have a desk by the window")]]),
    (y(1, "09-10"), 16, ["Priya Patel", "Sam Okafor", "Jordan Reyes"], [[("a", "Priya's wedding this weekend!!"), ("b", "I bought a suit"), ("a", "finally")],
                                                                        [("a", "I cried during the vows"), ("b", "everyone did")]]),
    (TODAY - dt.timedelta(days=60), 60, ["Priya Patel", "Theo Laurent", "Maya Chen"], [[("a", "12 miles today"), ("b", "who are you"), ("a", "a runner apparently")],
                                                                                        [("a", "race is in 6 weeks"), ("b", "we'll be at mile 10 with signs"), ("a", "please make them embarrassing")]]),
]
GROUPS = [  # name, app, members, years active (from, to), per year
    ("Roommates 🏠", "imessage", ["Jordan Reyes", "Sam Okafor"], (Y - 5, Y - 1), 300),
    ("Climbing crew 🧗", "imessage", ["Maya Chen", "Grace Kim", "Noah Bennett"], (Y - 3, Y), 260),
    ("Park family", "phone_whatsapp", ["Mom", "Dad"], (Y - 6, Y), 220),
    ("Lisbon '{}' ✈️".format(str(Y - 1)[2:]), "phone_whatsapp", ["Maya Chen", "Leo Martins", "Ines Duarte"], (Y - 1, Y - 1), 260),
    ("Tokyo trip 🗼", "imessage", ["Kenji Watanabe", "Jordan Reyes", "Kai Nakamura"], (Y - 1, Y - 1), 180),
    ("Trivia at The Owl", "imessage", ["Ruby Walsh", "Theo Laurent", "Maya Chen"], (Y - 1, Y), 240),
    ("college crew", "messenger", ["Sam Okafor", "Priya Patel", "Omar Haddad"], (Y - 6, Y - 3), 200),
]
GROUP_LINES = ["who's in for {day}?", "I'm in!", "same", "can't this week 😭", "{food} after?", "yes", "omg", "haha", "running late",
               "see you there", "who has the tickets", "I do!", "sending the link", "❤️", "this is the best group chat", "photo dump incoming",
               "did anyone see that", "lol", "wait what", "ok I'm here", "save me a seat", "bringing snacks", "happy birthday!! 🎉"]


def activity_hour(weekend):
    """When Riley texts: a little at lunch, most in the evening, later on weekends."""
    while True:
        h = R.gauss(20.5 if not weekend else 21.5, 2.6) if R.random() < 0.75 else R.gauss(12.5, 1.5)
        if 7 <= h < 26:
            return h


SEQ = iter(range(1, 10 ** 9))


def rid(prefix):
    return f"{prefix}-{next(SEQ):07d}"


# ---------------------------------------------------------------- write it

AVENUE = {
    "imessage": "Local SQLite: ~/Library/Messages/chat.db (synced from iPhone via iCloud Messages), plus the iPhone backup's sms.db.",
    "phone_whatsapp": "iPhone backup → iLEAPP → WhatsApp.",
    "instagram": "Meta Accounts Center > Download your information (JSON).",
    "messenger": "Meta Accounts Center > Download your information > Facebook (JSON, include Messages).",
    "discord": "Discord > Settings > Data & Privacy > Request all of my data. Only your own messages.",
}


def messages():
    """One-on-one chats in Messages, WhatsApp, Instagram and Messenger, group chats, and Discord (your side)."""
    out = {k: [] for k in ("imessage", "phone_whatsapp", "instagram", "messenger", "discord")}
    first_day = {}
    years = list(range(Y - 6, Y + 1))

    def burst(app, name, d, exchange, thread, thread_name, participants, group=False):
        me_first = R.random() < 0.5
        hour = activity_hour(d.weekday() >= 5)
        minute = R.uniform(0, 50)
        for who, text in exchange:
            me = (who == "a") == me_first
            author = "me" if me else (name if not group else pick(participants))
            minute += R.uniform(0.2, 6)
            ts = at(d, hour + minute // 60, minute % 60)
            text = fill(text)
            rec = dict(id=rid(app[:3]), kind="message", ts=ts, author=author, is_me=me, thread=thread, thread_name=thread_name,
                       participants=participants, text=text)
            if app == "imessage":
                rec["meta"] = {"service": "iMessage", "group": group, "copy": "mac"}
            elif app == "phone_whatsapp":
                rec["meta"] = {"artifact": "whatsApp", "category": "WhatsApp", "group": group}
            elif app in ("instagram", "messenger"):
                rec["meta"] = {"files": []}
            out[app].append(rec)
            if R.random() < 0.08:  # a quick reaction after
                minute += R.uniform(0.1, 2)
                out[app].append({**rec, "id": rid(app[:3]), "ts": at(d, hour + minute // 60, minute % 60), "is_me": not me,
                                 "author": "me" if not me else author, "text": pick(["haha", "😂", "❤️", "yes!!", "lol", "omg", "same", "100%", "🙌"])})

    for name, (counts, month, share, _calls) in CAST.items():
        for i, yr in enumerate(years):
            n = int(counts[i] * SCALE)
            if not n:
                continue
            lo = dt.date(yr, month if not first_day.get(name) else 1, 1)
            hi = min(dt.date(yr, 12, 31), TODAY)
            if lo > hi:
                continue
            first_day.setdefault(name, lo)
            pool = TOPICS.get(name, []) + GENERIC
            sent = 0
            while sent < n:
                d = lo + dt.timedelta(days=R.randrange((hi - lo).days + 1))
                ex = pick(pool) if R.random() < 0.85 else pick(GENERIC)
                r = R.random()
                app = "imessage"
                for a, f in share.items():
                    if r < f:
                        app = a
                        break
                    r -= f
                key = name.lower().replace(" ", "-")
                burst(app, name, d, ex, f"{app}:{key}", name, [name])
                sent += len(ex)
    for start, length, people, exes in EPISODES:
        for d in days(start, min(start + dt.timedelta(days=length), TODAY)):
            if R.random() < 0.55:
                name = pick(people)
                burst("imessage", name, d, pick(exes), f"imessage:{name.lower().replace(' ', '-')}", name, [name])
    for gname, app, members, (a, b), per_year in GROUPS:
        thread = f"{app}:group:{gname}"
        for yr in range(a, b + 1):
            lo, hi = dt.date(yr, 1, 1), min(dt.date(yr, 12, 31), TODAY)
            if gname.startswith("Lisbon"):
                lo, hi = y(1, "04-10"), y(1, "06-05")
            if gname.startswith("Tokyo"):
                lo, hi = y(1, "02-20"), y(1, "04-12")
            if gname.startswith("Trivia"):
                lo = max(lo, MOVE + dt.timedelta(days=30))
            if lo > hi:
                continue
            for _ in range(int(per_year * SCALE * 2.5 / 4)):
                d = lo + dt.timedelta(days=R.randrange((hi - lo).days + 1))
                ex = [(pick("ab"), x) for x in R.sample(GROUP_LINES, R.randint(2, 6))]
                burst(app, gname, d, ex, thread, gname, members, group=True)
    # Discord: a gaming server and a few DMs; the export keeps only what you wrote.
    for d in days(y(4, "01-10"), TODAY):
        if R.random() < 0.18:
            chan = pick(["#general", "#games", "#music", "#memes"])
            for _ in range(R.randint(1, 4)):
                out["discord"].append(dict(id=rid("dis"), kind="message", ts=at(d, activity_hour(True), R.randint(0, 59)), author="me",
                                           is_me=True, thread=f"discord:night-owls{chan}", thread_name=f"Night Owls {chan}",
                                           participants=["Night Owls"], text=fill(pick(
                                               ["gg everyone", "anyone up for a round?", "that last match was chaos", "brb snacks",
                                                "new {artist} single is so good", "I'm on in 10", "who's streaming tonight", "lmao",
                                                "patch notes are out", "ok one more game", "good night owls 🦉", "that boss took us 40 tries"])),
                                           meta={"channel_type": "GUILD_TEXT", "server": "Night Owls"}))
    for app, recs in out.items():
        with Writer(app, AVENUE[app], parser="desktop/scripts/demo_library.py", accumulate=False) as w:
            for r in sorted(recs, key=lambda r: r["ts"]):
                w.add(**r)
    return first_day


def calls():
    with Writer("calls", "Local SQLite: ~/Library/Application Support/CallHistoryDB/CallHistory.storedata.", parser="desktop/scripts/demo_library.py", accumulate=False) as w:
        recs = []
        for name, (counts, month, _s, per_year) in CAST.items():
            active = [Y - 6 + i for i, c in enumerate(counts) if c]
            for yr in active:
                for _ in range(per_year):
                    lo, hi = dt.date(yr, 1, 1), min(dt.date(yr, 12, 31), TODAY)
                    d = lo + dt.timedelta(days=R.randrange((hi - lo).days + 1))
                    if name in ("Mom", "Dad") and R.random() < 0.6:  # Sunday mornings
                        d -= dt.timedelta(days=(d.weekday() + 1) % 7)
                        hour = R.uniform(9.5, 11.5)
                    else:
                        hour = activity_hour(d.weekday() >= 5)
                    out = R.random() < 0.5
                    kind = pick(["Phone", "FaceTime Audio", "FaceTime Video"]) if name != "Mom" else pick(["Phone", "FaceTime Video", "FaceTime Video"])
                    secs = int(R.expovariate(1 / (1500 if name in ("Mom", "Dad", "Maya Chen") else 600))) + 20
                    if R.random() < 0.12:
                        secs = 0
                    recs.append(dict(id=rid("call"), kind="call", ts=at(d, hour), author="me" if out else name, is_me=out,
                                     thread=f"call:{name}", thread_name=name, participants=[name],
                                     text=f"{kind} call {'to' if out else 'from'} {name}, {secs // 60} min" if secs else f"Missed {kind} call {'to' if out else 'from'} {name}",
                                     meta={"direction": "outgoing" if out else "incoming", "type": kind, "seconds": secs, "location": "", "copy": "mac"}))
        for r in sorted(recs, key=lambda r: r["ts"]):
            w.add(**r)


# ---------------------------------------------------------------- photos

PHOTO_TAGS = {"sf": "San Francisco", "chicago": "Chicago", "tokyo": "Tokyo", "kyoto": "Kyoto", "lisbon": "Lisbon", "porto": "Porto", "nyc": "New York"}


def png(path, w, h, c1, c2):
    """A soft diagonal gradient, for when there are no pictures to cut photos from."""
    rows = []
    for j in range(h):
        row = bytearray([0])
        for i in range(w):
            t = (i / w + j / h) / 2
            row += bytes(int(c1[k] + (c2[k] - c1[k]) * t) for k in range(3))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 6)
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def photo_pool():
    """{place or 'home': [image files]}: crops of each picture (and their mirror images), so a grid of photos from the
    same trip doesn't show the same picture twice in a row."""
    out_dir = CORPUS / "files" / "photos"
    out_dir.mkdir(parents=True, exist_ok=True)
    pool = {}
    src = sorted(p for p in Path(ARGS.photos).iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")) if ARGS.photos else []
    if not src:
        for i in range(36):
            p = out_dir / f"drawn-{i:02d}.png"
            if not p.exists():
                hue = R.random()
                c1 = tuple(int(160 + 80 * math.sin(2 * math.pi * (hue + k / 3))) for k in range(3))
                c2 = tuple(int(90 + 70 * math.sin(2 * math.pi * (hue + 0.4 + k / 3))) for k in range(3))
                png(p, 96, 72, c1, c2)
            pool.setdefault("home", []).append(str(p))
        return pool
    for p in src:
        tag = PHOTO_TAGS.get(p.stem.split("_")[0].lower(), "home")
        info = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(p)], capture_output=True, text=True).stdout
        W = int(info.split("pixelWidth:")[1].split()[0])
        H = int(info.split("pixelHeight:")[1].split()[0])
        for k, (fw, fh, ox, oy) in enumerate([(1, 1, 0, 0), (0.62, 0.62, 0.05, 0.1), (0.62, 0.62, 0.36, 0.3), (0.55, 0.7, 0.4, 0.1),
                                               (0.7, 0.55, 0.1, 0.42), (0.5, 0.5, 0.25, 0.25)]):
            for flip in (False, True):
                out = out_dir / f"{p.stem}-{k}{'f' if flip else ''}.jpg"
                if not out.exists():
                    cw, ch = int(W * fw), int(H * fh)
                    cmd = ["sips", "-s", "format", "jpeg", "-s", "formatOptions", "82"]
                    if k:
                        cmd += ["--cropToHeightWidth", str(ch), str(cw), "--cropOffset", str(int(H * oy)), str(int(W * ox))]
                    if flip:
                        cmd += ["--flip", "horizontal"]
                    subprocess.run(cmd + ["-Z", "1100", str(p), "--out", str(out)], capture_output=True)
                if out.exists():
                    pool.setdefault(tag, []).append(str(out))
                    if tag in ("San Francisco", "home") or "autumn" in p.stem:  # for trips with no pictures of their own
                        pool.setdefault("outdoors", []).append(str(out))
    return pool


SCENES = {"San Francisco": ["Bridge", "Fog", "Ocean", "Sunset", "Hill", "Park"], "Chicago": ["Skyline", "Lake", "Beach", "River", "Architecture"],
          "Tokyo": ["Cityscape", "Night", "Cherry Blossom", "Tower", "Street"], "Kyoto": ["Temple", "Shrine", "Autumn", "Garden"],
          "Lisbon": ["Tram", "Street", "Rooftops", "Sunset"], "Porto": ["River", "Bridge", "Waterfront"], "New York": ["Skyline", "Street", "Snow"],
          "home": ["Food", "Plant", "Coffee", "Window", "Friends", "Dog"]}


def photos():
    pool = photo_pool()
    n = 0
    with Writer("photos", "Local SQLite, read in place: ~/Pictures/Photos Library.photoslibrary/database/Photos.sqlite.", parser="desktop/scripts/demo_library.py", accumulate=False) as w:
        recs = []
        for d in days(START, TODAY):
            city = where(d)
            trip = away(d)
            k = R.randint(18, 60) if trip else (R.choice([0, 0, 0, 1, 2, 3, 5]) + (R.randint(0, 8) if d.weekday() >= 5 else 0))
            if d == MOVE or (d.month, d.day) == (9, 13) and d.year == Y - 1:  # moving day; Priya's wedding
                k = 40
            lat0, lon0, region, country, _tz = CITY[city]
            companions = {"Tokyo": ["Jordan Reyes", "Kenji Watanabe"], "Kyoto": ["Jordan Reyes"], "Lisbon": ["Maya Chen", "Leo Martins", "Ines Duarte"],
                          "Porto": ["Maya Chen", "Leo Martins"], "Mexico City": ["Lucia Romero"], "Oaxaca": ["Lucia Romero"],
                          "New York": ["Mom", "Dad"], "London": ["Priya Patel"], "Paris": ["Priya Patel"], "Seattle": ["Sam Okafor"]}.get(city)
            for _ in range(k):
                n += 1
                hour = R.uniform(9, 21) if trip else R.choice([R.uniform(8, 9.5), R.uniform(12, 14), R.uniform(17, 21), R.uniform(10, 19)])
                hood = pick(HOOD.get(city, [city]))
                lat = lat0 + R.gauss(0, 0.02 if not trip else 0.035)
                lon = lon0 + R.gauss(0, 0.025 if not trip else 0.04)
                people = []
                if companions and R.random() < 0.35:
                    people = R.sample(companions, R.randint(1, len(companions)))
                elif not trip and R.random() < 0.18:
                    people = [pick(["Maya Chen", "Jordan Reyes", "Priya Patel", "Ruby Walsh", "Theo Laurent", "Grace Kim"] if d >= MOVE
                                   else ["Maya Chen", "Jordan Reyes", "Sam Okafor", "Priya Patel", "Grace Kim"])]
                # A picture of where they were if there is one (at home, most of the time: the rest is food, plants,
                # coffee); somewhere outdoors on a trip to a place with no pictures of its own.
                tag = city if city in pool and (trip or R.random() < 0.7) else ("outdoors" if trip else "home")
                if tag not in pool:
                    tag = "home" if "home" in pool else next(iter(pool))
                scenes = R.sample(SCENES.get(city if city in SCENES else "home", SCENES["home"]), 2)
                lines = ["Photo", f"Place: {hood if hood != city else city}, {city}, {region}, {country}" if hood != city else f"Place: {city}, {region}, {country}"]
                if people:
                    lines.append("People: " + ", ".join(people))
                lines.append("Scenes: " + ", ".join(scenes))
                video = R.random() < 0.05
                recs.append(dict(id=f"{R.getrandbits(32):08X}-{R.getrandbits(16):04X}-{R.getrandbits(16):04X}-{R.getrandbits(16):04X}-{R.getrandbits(48):012X}",
                                 kind="photo", ts=at(d, hour), author="me", is_me=True, participants=people or None,
                                 title=hood if hood != city else city, text="\n".join(lines),
                                 meta={"type": "video" if video else "photo", "lat": round(lat, 5), "lon": round(lon, 5), "filename": f"IMG_{n:04d}.{'MOV' if video else 'HEIC'}",
                                       **({"seconds": R.randint(4, 40)} if video else {}), "files": [pick(pool[tag])]}))
        for r in sorted(recs, key=lambda r: r["ts"]):
            w.add(**r)


# ---------------------------------------------------------------- calendar, reminders, notes

def calendar():
    recs = []

    def ev(d, h, hours, title, cal, all_day=False, location=None, text=None, people=None):
        start = at(d, h) if not all_day else f"{d.isoformat()}T00:00:00Z"
        end = (dt.datetime.fromisoformat(start.replace("Z", "+00:00")) + dt.timedelta(hours=hours)).isoformat().replace("+00:00", "Z") if not all_day \
            else f"{(d + dt.timedelta(days=1)).isoformat()}T00:00:00Z"
        meta = {"created": start, "modified": start, **({"all_day": True} if all_day else {}), **({"location": location} if location else {})}
        recs.append(dict(id=rid("cal"), kind="event", ts=start, ts_end=end, thread=f"cal:{cal}", thread_name=cal, title=title,
                         text=text or (f"{title}" + (f" at {location}" if location else "")), participants=people, meta=meta))

    for d in days(y(3, "06-01"), TODAY + dt.timedelta(days=90)):
        if d.weekday() in (1, 3) and not away(min(d, TODAY)) and R.random() < 0.8:
            ev(d, 19.5, 2, "Climbing 🧗", "Personal", location="First Ascent" if d >= MOVE else "Mission Cliffs", people=["Maya Chen"])
        if d.weekday() < 5 and not away(min(d, TODAY)):
            if d.weekday() == 0:
                ev(d, 10, 0.5, "Weekly planning", "Work")
            if d.weekday() == 2:
                ev(d, 14, 0.5, "1:1 with Marcus" if d >= NEW_JOB else "1:1 with Ethan", "Work")
            if d.weekday() == 4 and R.random() < 0.5:
                ev(d, 16, 1, "Demo hour", "Work")
        if d >= MOVE + dt.timedelta(days=30) and d.weekday() == 2 and R.random() < 0.7:
            ev(d, 19.5, 2, "Trivia at The Owl", "Personal", location="The Owl", people=["Ruby Walsh", "Theo Laurent"])
    # The dentist, every six months: the last one about seven weeks ago, the next in four months.
    d = TODAY - dt.timedelta(days=50)
    while d > START:
        ev(d, 8.5, 1, "Dentist: cleaning with Dr. Alvarez", "Personal", location="Alvarez Family Dental" if d >= MOVE else "Mission Dental Care")
        d -= dt.timedelta(days=182 + R.randint(-10, 10))
    ev(TODAY + dt.timedelta(days=130), 8.5, 1, "Dentist: cleaning with Dr. Alvarez", "Personal", location="Alvarez Family Dental")
    for i, (c, since) in enumerate(ROUTE[1:], 1):
        prev = ROUTE[i - 1][0]
        ev(since, 8, 4, f"Flight to {c}", "Travel", location=f"{prev} airport", text=f"Flight to {c} (from {prev})")
    for name, md in (("Mom", "03-22"), ("Dad", "11-02"), ("Maya Chen", "07-14"), ("Priya Patel", "01-30"), ("Jordan Reyes", "10-05"), ("Sam Okafor", "06-11")):
        for yr in range(Y - 6, Y + 1):
            ev(dt.date(yr, int(md[:2]), int(md[3:])), 0, 24, f"{FIRST[name]}'s birthday 🎂", "Birthdays", all_day=True)
    ev(y(1, "09-13"), 16, 8, "Priya & Dev's wedding 💍", "Personal", location="Napa Valley", people=["Priya Patel"])
    ev(MOVE, 8, 10, "Moving day 📦", "Personal", location="Wicker Park, Chicago", people=["Maya Chen"])
    ev(y(1, "07-15"), 17, 1, "Lease signing", "Personal", location="Wicker Park, Chicago")
    ev(NEW_JOB, 9, 8, "First day at Lumen Labs", "Work", location="Lumen Labs, West Loop")
    ev(RACE, 7, 3, "Lakefront Half Marathon 🏃", "Personal", location="Lakefront Trail, Chicago")
    for k in range(1, 10):
        ev(RACE - dt.timedelta(days=7 * k - 5), 8, 1.5, f"Long run: {max(4, 13 - k)} miles", "Personal", location="Lakefront Trail")
    with Writer("calendar", "Local SQLite: ~/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb.", parser="desktop/scripts/demo_library.py", accumulate=False) as w:
        for r in sorted(recs, key=lambda r: r["ts"]):
            w.add(**r)


def notes_and_reminders():
    notes = [
        ("Groceries", "limes\nthe good bread\noat milk\ngreek yogurt\nspinach\ncoffee beans\ndish soap"),
        ("Lisbon + Porto", "Day 1: Alfama, miradouro at sunset (Ines says Santa Luzia)\nDay 2: Belém, pastéis de nata warm\nDay 3: LX Factory\nDay 5: train to Porto 9am\nPorto: Ribeira, port cellars, Livraria Lello (go early)"),
        ("Tokyo / Kyoto", "Shibuya, meet Kenji\nTsukiji outer market breakfast\nteamLab\nJR pass for Kyoto\nFushimi Inari at 7am\nArashiyama bamboo\nramen list from Kenji (40 places??)"),
        ("Moving to Chicago", "cancel PG&E\nforward mail\nbook movers (Aug 1)\nnew renter's insurance\nwinter coat!!\nfind a climbing gym (First Ascent?)\nlibrary card"),
        ("Books to read", "Piranesi\nThe Overstory\nTomorrow, and Tomorrow, and Tomorrow\nProject Hail Mary\nStation Eleven\nBraiding Sweetgrass"),
        ("Half marathon plan", "Weeks 1-4: 3 runs, long run 6-8 mi\nWeeks 5-8: tempo on Tuesdays, long run 9-11 mi\nWeeks 9-12: taper last 2 weeks\nRace day: gels at mile 5 and 9, don't start too fast"),
        ("Gift ideas", "Mom: the scarf from the market\nDad: that grilling book\nMaya: chalk bag, the purple one\nPriya: framed wedding photo"),
        ("Recipes", "Mom's kimchi jjigae: aged kimchi, pork belly, tofu, gochugaru, simmer 30 min\nShakshuka: peppers, onion, tomatoes, cumin, eggs on top"),
        ("Apartment wishlist", "a rug for the living room\nshelves for the books (so many books)\na plant that survives winter"),
        ("Ideas", "an app that keeps all your data in one place??\nweekend trip to Milwaukee\nlearn to make sourdough"),
    ]
    with Writer("apple_notes", "Local SQLite: ~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite.", parser="desktop/scripts/demo_library.py", accumulate=False) as w:
        for i, (title, body) in enumerate(notes):
            d = TODAY - dt.timedelta(days=R.randint(5, 900))
            if title.startswith("Lisbon"):
                d = y(1, "04-20")
            if title.startswith("Tokyo"):
                d = y(1, "02-25")
            if title.startswith("Moving"):
                d = y(1, "06-25")
            if title.startswith("Half"):
                d = TODAY - dt.timedelta(days=70)
            w.add(id=f"note-{i}", kind="note", ts=at(d, 21), ts_end=at(min(d + dt.timedelta(days=R.randint(0, 30)), TODAY), 22), author="me", is_me=True,
                  thread="Notes", thread_name="Notes", title=title, text=f"{title}\n\n{body}", meta={"modified": at(d, 22)})
        for k in range(60):  # shorter notes over the years
            d = START + dt.timedelta(days=R.randrange((TODAY - START).days))
            t = fill(pick(["{food} place on the corner, try it", "watch {show}", "{book}: loved the ending", "call Mom about the holidays",
                           "ask {friend} about the trip", "passport renewal before spring", "{artist} concert tickets go on sale friday"]).replace("{friend}", pick(list(CAST)[:8])))
            w.add(id=f"note-x{k}", kind="note", ts=at(d, 20), ts_end=at(d, 20), author="me", is_me=True, thread="Notes", thread_name="Notes",
                  title=t[:40], text=t, meta={"modified": at(d, 20)})
    with Writer("reminders", "Local SQLite: ~/Library/Group Containers/group.com.apple.reminders/Container_v1/Stores/Data-*.sqlite.", parser="desktop/scripts/demo_library.py", accumulate=False) as w:
        items = ["Pay rent", "Call Mom", "Book dentist", "Renew passport", "Water the plants", "Return library books", "Send Priya the photos",
                 "Buy race gels", "Schedule oil change", "Pick up dry cleaning", "Venmo Maya for groceries", "Cancel old gym membership", "Order chalk"]
        for k in range(220):
            d = START + dt.timedelta(days=R.randrange((TODAY - START).days + 1))
            t = pick(items)
            done = d < TODAY - dt.timedelta(days=3) or R.random() < 0.5
            w.add(id=f"rem-{k}", kind="reminder", ts=at(d, 9), author="me", is_me=True, thread="Reminders", thread_name="Reminders", title=t,
                  text=t + (" (done)" if done else ""), meta={"completed": done, "modified": at(d, 18), **({"completed_at": at(d, 18)} if done else {}), "due": at(d, 9)})


# ---------------------------------------------------------------- email

def email():
    recs = []

    def mail(d, h, frm, name, subject, body, labels=("INBOX",), to=None, me=False, thread=None):
        recs.append(dict(id=rid("gm"), kind="email", ts=at(d, h), author="me" if me else name, is_me=me, thread=thread or subject.lower()[:40],
                         thread_name=subject, participants=[name], title=subject, text=f"{subject}\n\n{body}",
                         meta={"from": f"{name} <{frm}>" if not me else f"{ME['name']} <{ME['email']}>", "to": to or ME["email"], "labels": list(labels)}))

    for d in days(START, TODAY):
        if d.weekday() == 0:
            mail(d, 7, "no-reply@strava.com", "Strava", "Your weekly recap", f"You ran {R.randint(8, 34)} km this week across {R.randint(2, 5)} activities.", ("CATEGORY_UPDATES",))
        if d.weekday() == 5 and R.random() < 0.7:
            mail(d, 8, "cooking@nytimes.com", "NYT Cooking", pick(["Weekend cooking: 5 cozy soups", "The best summer salads", "Sheet-pan dinners for busy weeks", "Bake this weekend"]),
                 "Recipes we think you'll like this weekend.", ("CATEGORY_PROMOTIONS",))
        if R.random() < 0.05:
            mail(d, 12, "auto-confirm@amazon.com", "Amazon", f"Your order of {pick(['running socks', 'a desk lamp', 'chalk', 'a rice cooker', 'a winter hat', 'headphones', 'a phone case'])} has shipped",
                 "Arriving Thursday.", ("CATEGORY_UPDATES",))
        if R.random() < 0.03:
            mail(d, 22, "noreply@uber.com", "Uber", f"Your {pick(['Monday', 'Friday', 'Saturday', 'Sunday'])} evening trip with Uber", f"Total ${R.randint(9, 38)}.{R.randint(10, 99)}", ("CATEGORY_UPDATES",))
        if d.day == 1:
            mail(d, 6, "no-reply@spotify.com", "Spotify", "Your Spotify Premium receipt", "Thanks for being a Premium member. $11.99", ("CATEGORY_UPDATES",))
    for i, (c, since) in enumerate(ROUTE[1:], 1):
        booked = since - dt.timedelta(days=R.randint(20, 60))
        mail(booked, 20, "unitedairlines@united.com", "United Airlines", f"Your trip confirmation: {ROUTE[i - 1][0]} to {c}", f"Confirmation {R.choice('ABCDEFGHJKLMNPQRSTUVWXYZ')}{R.randint(10000, 99999)}. Departs {since:%b %d}.", ("CATEGORY_UPDATES",))
        if c not in ("San Francisco", "Chicago"):
            mail(booked + dt.timedelta(days=2), 21, "automated@airbnb.com", "Airbnb", f"Reservation confirmed in {c}", f"You're going to {c}! Check-in {since:%b %d}.", ("CATEGORY_UPDATES",))
    d = TODAY - dt.timedelta(days=50)
    while d > START:
        mail(d - dt.timedelta(days=3), 10, "appointments@dental.example", "Alvarez Family Dental" if d >= MOVE else "Mission Dental Care",
             "Appointment reminder", f"This is a reminder of your cleaning on {d:%A, %B %d} at 8:30 am with Dr. Alvarez.")
        d -= dt.timedelta(days=182)
    mail(y(1, "07-21"), 15, "people@lumenlabs.example", "Lumen Labs", "Your offer from Lumen Labs", "We're thrilled to offer you the role of Senior Software Engineer. Start date: September 8.")
    mail(NEW_JOB - dt.timedelta(days=3), 9, "it@lumenlabs.example", "Lumen Labs IT", "Welcome! Your laptop is on its way", "Your laptop ships today. See you Monday!")
    mail(y(1, "07-25"), 11, "hr@fernwood.example", "Fernwood People Team", "Your last day", "Thank you for four great years. Your final paycheck will arrive August 15.", to=ME["old_work"])
    mail(y(1, "06-12"), 18, "priya.patel@example.com", "Priya Patel", "You're invited: Priya & Dev 💍", "We'd love for you to join us in Napa on September 13. Dancing until late!")
    mail(y(1, "06-30"), 13, "leasing@wickerflats.example", "Wicker Flats Leasing", "Your lease is ready to sign", "Unit 3B, 2 bedrooms. Move-in August 1.")
    mail(TODAY - dt.timedelta(days=80), 9, "register@lakefronthalf.example", "Lakefront Half Marathon", "You're registered!", f"See you on {RACE:%B %d}. Bib pickup is the day before.")
    mail(TODAY - dt.timedelta(days=12), 7, "noreply-takeout@google.com", "Google Takeout", "Your Google data is ready to download", "Your Google data archive is ready. Download it by the expiry date.")
    for k in range(70):
        d = START + dt.timedelta(days=R.randrange((TODAY - START).days))
        mail(d, 19, "mom.park@example.com", "Mom", pick(["Recipe you asked for", "Photos from the weekend", "Thanksgiving plans", "Article you might like", "Did you see this?"]),
             pick(["Love you! Call me this weekend.", "Here are the pictures from Sunday.", "Let me know what you think.", "Dad says hi."]))
    for k in range(260):
        d = START + dt.timedelta(days=R.randrange((TODAY - START).days))
        if d.weekday() >= 5:
            continue
        work = "Lumen Labs" if d >= NEW_JOB else "Fernwood"
        mail(d, R.uniform(9, 17), "notifications@github.example", f"{work} GitHub", pick([f"[{work.lower()}/web] Review requested", f"[{work.lower()}/api] PR merged", "CI failed on main", "Weekly digest"]),
             "You were mentioned in a pull request.", ("CATEGORY_UPDATES",), to=ME["work"] if d >= NEW_JOB else ME["old_work"])
    with Writer("gmail", "Google Takeout (takeout.google.com) > Mail (mbox).", parser="desktop/scripts/demo_library.py", accumulate=False) as w:
        for r in sorted(recs, key=lambda r: r["ts"]):
            w.add(**r)


# ---------------------------------------------------------------- health, music, browsing

def health():
    with Writer("health", "iPhone encrypted local backup → HealthDomain/Health/healthdb_secure.sqlite.", parser="desktop/scripts/demo_library.py", accumulate=False) as w:
        for d in days(y(3, "01-01"), TODAY - dt.timedelta(days=1)):
            trip = away(d)
            training = (RACE - dt.timedelta(days=100)) <= d
            steps = max(800, int(R.gauss(13500 if trip else (9800 if training else 7600), 2600)))
            if d.weekday() >= 5 and not trip:
                steps = int(steps * R.uniform(0.8, 1.4))
            km = round(steps * 0.00074 + (R.uniform(5, 16) if training and d.weekday() in (1, 3, 5) else 0), 2)
            flights = R.randint(2, 18)
            kcal = int(steps * 0.04 + R.uniform(80, 260))
            tz = CITY[where(d)][4]
            parts = [f"{steps:,} steps", f"{km:.1f} km walked/run", f"{flights} flights climbed", f"{kcal} active kcal"]
            w.add(id=f"day:{d.isoformat()}", kind="health_day", ts=f"{d.isoformat()}T00:00:00", author="me", is_me=True, title=f"Health {d.isoformat()}",
                  text=f"Health {d.isoformat()} ({tz}): " + ", ".join(parts), meta={"steps": steps, "distance_km": km, "flights": flights, "active_kcal": kcal, "tz": tz})
        for d in days(y(1, "01-01"), TODAY - dt.timedelta(days=1)):
            bed = R.gauss(23.6 if d.weekday() < 4 else 24.6, 0.6)
            asleep = max(4.5, R.gauss(7.2, 0.7))
            tz = CITY[where(d)][4]
            a = (dt.datetime(d.year, d.month, d.day, tzinfo=ZoneInfo(tz)) + dt.timedelta(hours=bed)).replace(microsecond=0)
            b = a + dt.timedelta(hours=asleep + 0.3)
            w.add(id=f"sleep:{d.isoformat()}", kind="sleep", ts=a.astimezone(UTC).isoformat(), ts_end=b.astimezone(UTC).isoformat(), author="me", is_me=True,
                  title=f"Sleep {b.date().isoformat()}", text=f"Slept {asleep:.1f} h, {a:%a %b %d %H:%M} to {b:%H:%M} ({tz}); core {asleep * 0.55:.1f} h, deep {asleep * 0.18:.1f} h, rem {asleep * 0.22:.1f} h",
                  meta={"asleep_min": round(asleep * 60), "in_bed_min": round((asleep + 0.3) * 60), "tz": tz})


TRACKS = [("Phoebe Bridgers", "Punisher", ["Kyoto", "Garden Song", "Moon Song", "I Know the End", "Motion Sickness"]),
          ("Japanese Breakfast", "Jubilee", ["Be Sweet", "Kokomo, IN", "Slide Tackle", "Paprika"]),
          ("Khruangbin", "Mordechai", ["Time (You and I)", "So We Won't Forget", "Pelota"]),
          ("Bon Iver", "i,i", ["Hey, Ma", "Naeem", "Faith", "Holocene"]),
          ("Mitski", "The Land Is Inhospitable and So Are We", ["My Love Mine All Mine", "Bug Like an Angel", "Heaven", "Nobody"]),
          ("Fred again..", "Actual Life 3", ["Delilah (pull me out of this)", "Danielle (smile on my face)", "Adore U"]),
          ("Big Thief", "Dragon New Warm Mountain I Believe in You", ["Change", "Simulation Swarm", "Spud Infinity", "Not"]),
          ("Caroline Polachek", "Desire, I Want to Turn Into You", ["Welcome to My Island", "Bunny Is a Rider", "Sunset"]),
          ("Bad Bunny", "Un Verano Sin Ti", ["Tití Me Preguntó", "Me Porto Bonito", "Ojitos Lindos", "Moscow Mule"]),
          ("Tame Impala", "The Slow Rush", ["Borderline", "Lost in Yesterday", "Breathe Deeper", "Let It Happen"]),
          ("Rosalía", "Motomami", ["DESPECHÁ", "Saoko", "Candy", "Malamente"]),
          ("Kendrick Lamar", "GNX", ["Not Like Us", "luther", "squabble up", "tv off"]),
          ("Clairo", "Charm", ["Sexy to Someone", "Juna", "Echo"]),
          ("SZA", "SOS", ["Kill Bill", "Snooze", "Good Days"]),
          ("Vampire Weekend", "Only God Was Above Us", ["Capricorn", "Classical", "Harmony Hall"]),
          ("Frank Ocean", "Blonde", ["Pink + White", "Nights", "Ivy", "Self Control"]),
          ("Beabadoobee", "This Is How Tomorrow Moves", ["Ever Seen", "Glue Song", "Coffee"]),
          ("Kacey Musgraves", "Golden Hour", ["Slow Burn", "Rainbow", "Butterflies"]),
          ("The National", "I Am Easy to Find", ["Light Years", "Rylan", "Bloodbuzz Ohio"]),
          ("Mac DeMarco", "Salad Days", ["Chamber of Reflection", "Salad Days", "My Kind of Woman"]),
          ("Hozier", "Unreal Unearth", ["Too Sweet", "Francesca", "Cherry Wine"]),
          ("Men I Trust", "Untourable Album", ["Show Me How", "Tailwhip", "Lauren"]),
          ("Snail Mail", "Valentine", ["Valentine", "Pristine", "Forever (Sailing)"]),
          ("Jungle", "Volcano", ["Back On 74", "Casio", "Busy Earnin'"])]
# A favorite for each season (quarter), oldest first: what was on most, the way taste goes.
ERAS = ["Bon Iver", "Frank Ocean", "Tame Impala", "Mac DeMarco", "Phoebe Bridgers", "Phoebe Bridgers", "The National", "Japanese Breakfast",
        "Bad Bunny", "Khruangbin", "Kacey Musgraves", "Mitski", "Big Thief", "Snail Mail", "Rosalía", "Vampire Weekend", "Fred again..",
        "Beabadoobee", "Caroline Polachek", "Jungle", "Phoebe Bridgers", "Men I Trust", "Kendrick Lamar", "Hozier", "Mitski", "Clairo", "SZA", "Clairo"]


def music():
    with Writer("spotify", "Spotify account > Privacy settings > Download your data (Extended streaming history).", parser="desktop/scripts/demo_library.py", accumulate=False) as w:
        k = 0
        by_name = {t[0]: t for t in TRACKS}
        for d in days(START, TODAY):
            q = ((d.year - START.year) * 4 + (d.month - 1) // 3) % len(ERAS)
            fav = by_name[ERAS[q]]
            for _ in range(R.randint(1, 11)):
                artist, album, songs = fav if R.random() < 0.4 else pick(TRACKS)
                k += 1
                song = pick(songs) if R.random() < 0.85 else songs[0]
                w.add(id=f"sp-{k}", kind="media", ts=at(d, R.choice([R.uniform(7.5, 9.5), R.uniform(12, 18), R.uniform(18, 23)])), author="me", is_me=True,
                      title=song, text=f"{song} — {artist} — {album} (Spotify)", meta={"artist": artist, "album": album, "seconds": R.randint(140, 290), "platform": "ios"})
            if R.random() < 0.012:  # a song on repeat all day
                artist, album, songs = fav
                song = songs[0]
                for _ in range(R.randint(6, 14)):
                    k += 1
                    w.add(id=f"sp-{k}", kind="media", ts=at(d, R.uniform(9, 23)), author="me", is_me=True, title=song,
                          text=f"{song} — {artist} — {album} (Spotify)", meta={"artist": artist, "album": album, "seconds": R.randint(160, 260), "platform": "ios"})


# What Riley looked up: each year has its own (the welcome tour's), some things every year, and the weeks before a
# trip are about where they're going.
SEARCH_YEARS = [
    ["sourdough starter", "how to make sourdough starter", "why is my sourdough dense", "home workout no equipment", "zoom backgrounds", "banana bread recipe",
     "1000 piece puzzle", "seattle ferry", "pike place market", "best hikes near seattle"],
    ["climbing shoes sizing", "what size climbing shoes", "vancouver granville island", "muir woods reservations", "is muir woods open", "camping gear checklist",
     "bouldering grades", "two person tent", "how to set up a tent alone", "stanley park bike rental"],
    ["london in june", "paris museums pass", "eurostar tickets", "is the eurostar worth it", "louvre tickets", "react hooks tutorial", "how to beat jet lag",
     "what to see in paris in 3 days", "borough market", "london tube map"],
    ["austin bbq", "franklin barbecue line", "typescript generics", "what are typescript generics", "running shoes for beginners", "how often to replace running shoes",
     "lease renewal negotiation", "how to negotiate rent", "postgres index slow query", "barton springs"],
    ["oaxaca food tour", "is oaxaca safe", "spanish lessons online", "mezcal tasting oaxaca", "day of the dead oaxaca", "mexico city tacos al pastor", "what is mole negro",
     "mexico city to oaxaca flight", "tlayuda", "monte alban tickets"],
    ["tokyo cherry blossom forecast", "is the jr pass worth it", "fushimi inari early morning", "kyoto bamboo forest", "lisbon pastel de nata best", "lisbon tram 28",
     "porto port cellars", "lisbon to porto train", "chicago apartments wicker park", "moving checklist", "how to pack books for moving", "how cold does chicago get",
     "chicago winter coat", "renters insurance chicago", "what to wear to a wedding in napa", "first ascent climbing chicago"],
    ["half marathon training plan", "how to train for a half marathon", "what pace for a 2 hour half marathon", "running gels", "should you run the day before a race",
     "knee pain after running", "lakefront trail mileage", "denver in february", "red rocks amphitheatre", "lumen labs office west loop"],
]
EVERGREEN = ["weather", "ramen near me", "google translate", "time in tokyo", "kimchi jjigae recipe", "piranesi book", "how to bleed a radiator", "standing desk",
             "python asyncio tutorial", "best tacos near me", "bon iver tour", "sunset time"]
SITES = [("https://www.nytimes.com/", "The New York Times"), ("https://www.reddit.com/r/climbing/", "r/climbing"), ("https://github.com/", "GitHub"),
         ("https://www.strava.com/dashboard", "Strava"), ("https://news.ycombinator.com/", "Hacker News"), ("https://www.youtube.com/", "YouTube"),
         ("https://www.chicagotribune.com/", "Chicago Tribune"), ("https://www.allrecipes.com/", "Allrecipes"), ("https://maps.google.com/", "Google Maps"),
         ("https://www.wikipedia.org/", "Wikipedia"), ("https://www.goodreads.com/", "Goodreads"), ("https://www.airbnb.com/", "Airbnb")]
DISHES = ["sourdough", "ramen from scratch", "tacos al pastor", "carbonara", "kimchi jjigae", "pad thai", "khachapuri", "dumplings", "shakshuka",
          "bagels", "focaccia", "pho", "birria", "mapo tofu", "croissants", "paella", "bibimbap", "gnocchi", "katsu curry", "lemon tart"]
TECH = ["TypeScript", "Postgres", "React", "Rust", "Docker", "SQLite", "Kubernetes", "Python", "Bun", "Redis", "GraphQL", "WebAssembly", "Go", "Svelte"]
WALKS = ["Shibuya at night", "Shinjuku in the rain", "Fushimi Inari at dawn", "Kyoto in autumn", "Asakusa", "Nakameguro", "Gion", "Arashiyama"]
RUNS = ["How to Train for Your First Half Marathon", "Fix your running form", "What to eat before a race", "Easy runs explained", "Tempo runs, explained",
        "Long run mistakes", "Taper week", "Strength training for runners", "Race day pacing", "Shoe review: daily trainers"]
BUILDINGS = ["The Rookery", "Marina City", "The Wrigley Building", "Tribune Tower", "The Monadnock", "Aqua Tower", "The Robie House", "Union Station",
             "The Chicago Cultural Center", "The L, explained", "Willis Tower", "The Merchandise Mart"]
SF = ["Lands End", "Sutro Baths", "the Golden Gate Bridge", "Twin Peaks", "Ocean Beach", "the Presidio", "Alcatraz", "Bernal Hill"]
TOPICS_K = ["the Moon disappeared", "you stopped sleeping", "the Sun went out", "a black hole hit Earth", "we lived on Mars", "the oceans dried up",
            "you fell into Jupiter", "bees went extinct", "the Earth stopped spinning", "you lived forever"]
# A channel's videos: titles from a few parts, so most are different, as a real channel's are; a few favorites
# watched again and again.
CHANNELS = {"Tiny Desk Concerts": lambda: f"{pick(TRACKS)[0]}: Tiny Desk {pick(['Concert', '(Home) Concert'])}",
            "Climbing Daily": lambda: f"Climbing Daily Ep. {R.randint(1500, 2100)}",
            "Binging with Babish": lambda: f"{pick(DISHES).capitalize()} {pick(['from The Bear', 'from Ratatouille', 'from Chef', 'three ways', 'for beginners', 'from Studio Ghibli'])}",
            "Running Channel": lambda: pick(RUNS) if R.random() < 0.4 else f"{R.randint(5, 20)} mile long run, {pick(['easy', 'tempo', 'progression', 'hilly'])}",
            "Kurzgesagt": lambda: f"What if {pick(TOPICS_K)}?",
            "Japan Walk": lambda: f"{pick(WALKS)} {pick(['walk 4K', 'at night 4K', 'in the rain 4K', 'at sunrise'])}",
            "Chicago Architecture Center": lambda: f"{pick(BUILDINGS)}{pick(['', ', explained', ': a tour', ' at 100'])}",
            "Fireship": lambda: pick([f"{pick(TECH)} in 100 seconds", f"I tried {pick(TECH)} for {R.randint(3, 30)} days", f"{pick(TECH)} vs {pick(TECH)}"]),
            "Fog City Films": lambda: f"{pick(SF)} {pick(['in fog 4K', 'at sunset', 'from above', 'at dawn'])}",
            "Lisbon Walks": lambda: f"{pick(['Alfama', 'Baixa', 'Bairro Alto', 'Belém', 'Ribeira', 'Sintra'])} {pick(['walk 4K', 'at golden hour', 'at night'])}"}
SEEN = collections.Counter()
# How often each comes up, by how many different videos it has (a channel with ten videos can't fill a year).
CHANNEL_WEIGHT = {"Climbing Daily": 3, "Fireship": 3, "Binging with Babish": 2, "Running Channel": 1.5, "Tiny Desk Concerts": 1.5,
                  "Chicago Architecture Center": 1, "Japan Walk": 1, "Fog City Films": 0.8, "Lisbon Walks": 0.5, "Kurzgesagt": 0.4}
FAVORITES = [("How to Train for Your First Half Marathon", "Running Channel"), ("Phoebe Bridgers: Tiny Desk Concert", "Tiny Desk Concerts"),
             ("Fushimi Inari at dawn walk 4K", "Japan Walk"), ("Sourdough for beginners", "Binging with Babish")]
SHOWS = ["The Great British Baking Show", "Our Planet", "Chef's Table", "The Bear", "Midnight Diner"]


def search_text(d):
    """What Riley searched on day d: that year's things most, the trip ahead in the weeks before it."""
    for i, (c, since) in enumerate(ROUTE[1:], 1):
        if c not in ("San Francisco", "Chicago") and 0 <= (since - d).days <= 40 and R.random() < 0.2:
            return pick([f"{c.lower()} {w}" for w in ("things to do", "restaurants", "weather in", "neighborhoods", "day trips", "airport to city")])
    return pick(SEARCH_YEARS[min(6, max(0, d.year - START.year))]) if R.random() < 0.7 else pick(EVERGREEN)


def browsing():
    with Writer("browser_history", "Local SQLite: Safari's ~/Library/Safari/History.db and Chrome's History.", parser="desktop/scripts/demo_library.py", accumulate=False) as w:
        k = 0
        for d in days(TODAY - dt.timedelta(days=420), TODAY):
            for _ in range(R.randint(4, 26)):
                k += 1
                if R.random() < 0.35:
                    q = search_text(d)
                    w.add(id=f"bh-{k}", kind="search", ts=at(d, activity_hour(d.weekday() >= 5)), author="me", is_me=True, thread="Safari", thread_name="Safari",
                          title=q, text=q, url=f"https://www.google.com/search?q={q.replace(' ', '+')}", meta={"other_device": False, "visit_count": 1, "engine": "Google"})
                else:
                    url, name = pick(SITES)
                    w.add(id=f"bh-{k}", kind="visit", ts=at(d, activity_hour(d.weekday() >= 5)), author="me", is_me=True, thread="Safari", thread_name="Safari",
                          title=name, text=f"{name} {url}", url=url, meta={"other_device": R.random() < 0.3, "visit_count": R.randint(1, 40)})
    # Google's My Activity, as Takeout writes it: a search's title is what was searched; a video's text is its title, then
    # its channel (an artist's "- Topic" channel is YouTube Music).
    with Writer("google_activity", "Google Takeout > My Activity (JSON) + YouTube and YouTube Music.", parser="desktop/scripts/demo_library.py", accumulate=False) as w:
        k = 0
        for d in days(START, TODAY):
            for _ in range(R.randint(0, 9)):
                k += 1
                r = R.random()
                if r < 0.45:
                    q = search_text(d)
                    w.add(id=f"ga-{k}", kind="search", ts=at(d, activity_hour(d.weekday() >= 5)), author="me", is_me=True, thread="Search", thread_name="Search",
                          title=q, text=q, url=f"https://www.google.com/search?q={q.replace(' ', '+')}", meta={"product": "Search"})
                elif r < 0.64:
                    if R.random() < 0.12:
                        artist, _, songs = pick(TRACKS)
                        title, channel = pick(songs), f"{artist} - Topic"
                    else:
                        channel = R.choices(list(CHANNEL_WEIGHT), weights=list(CHANNEL_WEIGHT.values()))[0]
                        for _ in range(12):  # a video once or twice: only the favorites get watched again and again
                            title = CHANNELS[channel]()
                            if SEEN[title] < 2:
                                break
                        else:
                            channel, title = "Climbing Daily", f"Climbing Daily Ep. {len(SEEN) + 2200}"
                        SEEN[title] += 1
                        if R.random() < 0.02:
                            title, channel = pick(FAVORITES)
                    w.add(id=f"ga-{k}", kind="media", ts=at(d, R.uniform(19, 25) if R.random() < 0.8 else R.uniform(12, 14)), author="me", is_me=True, thread="YouTube", thread_name="YouTube",
                          title=title, text=f"{title}\n{channel}", url=f"https://www.youtube.com/watch?v={R.getrandbits(40):010x}", meta={"product": "YouTube"})
                else:
                    c = where(d)
                    w.add(id=f"ga-{k}", kind="activity", ts=at(d, R.uniform(10, 20)), author="me", is_me=True, thread="Maps", thread_name="Maps",
                          title=f"Directions to {pick(HOOD.get(c, [c]))}", text=f"Directions to {pick(HOOD.get(c, [c]))}, {c}", meta={"product": "Maps"})
    # Netflix on the iPhone (iLEAPP's view of the app): a show a season at a time, on winter evenings mostly.
    with Writer("phone_netflix", "iPhone backup → iLEAPP → Netflix.", parser="desktop/scripts/demo_library.py", accumulate=False) as w:
        k = 0
        watched = collections.Counter()  # episodes in order, a season at a time
        for d in days(START, TODAY):
            if R.random() < (0.16 if d.month in (11, 12, 1, 2) else 0.05):
                show = SHOWS[(d.year * 2 + (d.month > 6)) % len(SHOWS)]
                for e in range(R.randint(1, 4)):
                    k += 1
                    n = watched[show]
                    watched[show] += 1
                    name = f"{show}: Season {n // 8 + 1}: Episode {n % 8 + 1}"
                    w.add(id=f"nf-{k}", kind="media", ts=at(d, 20.5 + e * 0.8), title=name, text=f"Netflix: {name}",
                          meta={"artifact": "netflix", "category": "Netflix", "fields": {"Displayed Title": name, "Entity Type (as stored)": "episode"}})


# ---------------------------------------------------------------- what Riley made, and the rest

def made():
    with Writer("git_commits", "Local: .git folders under ~/Documents, ~/Desktop and code folders; git log --all.", parser="desktop/scripts/demo_library.py", accumulate=False) as w:
        repos = {"trail-weather": ["Add hourly forecast for trailheads", "Fix wind speed units", "Cache NOAA responses", "Show sunrise and sunset", "Dark mode"],
                 "recipe-box": ["Import recipes from a URL", "Scale servings", "Tag recipes", "Fix the search ranking", "Add Mom's kimchi jjigae"],
                 "dotfiles": ["zsh: faster prompt", "git aliases", "Neovim: LSP setup", "brew bundle"],
                 "race-pacer": ["Pace calculator", "Split table for the half", "Export to watch", "Negative-split mode"]}
        k = 0
        for d in days(START, TODAY):
            if d.weekday() >= 5 and R.random() < 0.3 or R.random() < 0.06:
                repo = pick(list(repos)) if d < TODAY - dt.timedelta(days=100) else pick(["race-pacer", "recipe-box", "trail-weather"])
                for _ in range(R.randint(1, 4)):
                    k += 1
                    msg = pick(repos[repo])
                    w.add(id=f"git-{k}", kind="commit", ts=at(d, R.uniform(10, 23)), author=ME["name"], is_me=True, thread=repo, thread_name=repo, title=msg,
                          text=f"{msg}\n\n{repo}", meta={"repo": f"~/Developer/{repo}", "email": ME["email"], "remote": f"github.com/rileyp/{repo}"})
    with Writer("ai_coding", "Local JSONL: Claude Code ~/.claude/projects, Codex ~/.codex/sessions.", parser="desktop/scripts/demo_library.py", accumulate=False) as w:
        asks = [("race-pacer", ["Add a negative-split mode to the pace calculator", "Done: pacer.py now takes --negative-split and slows the first half by 2%."]),
                ("recipe-box", ["Make the search rank title matches first", "Updated search.py: title hits score 3x, then ingredients, with a test."]),
                ("trail-weather", ["Cache the NOAA responses for 10 minutes", "Added an in-memory TTL cache around fetch_forecast(); the tests stub the clock."]),
                ("recipe-box", ["Scale servings without rounding 1/3 cup to 0.33", "Added fractions.py; quantities stay as fractions when they're common ones."])]
        k = 0
        for d in days(TODAY - dt.timedelta(days=300), TODAY):
            if R.random() < 0.12:
                repo, (q, a) = pick(asks)
                k += 1
                s = f"session-{k}"
                w.add(id=f"ai-{k}a", kind="ai_turn", ts=at(d, 21), author="me", is_me=True, thread=s, thread_name=q[:50], text=q, meta={"cwd": f"~/Developer/{repo}", "tool": "claude-code"})
                w.add(id=f"ai-{k}b", kind="ai_turn", ts=at(d, 21, 4), author="claude", is_me=False, thread=s, thread_name=q[:50], text=a, meta={"cwd": f"~/Developer/{repo}", "tool": "claude-code", "model": "claude-sonnet"})
    with Writer("documents", "Filesystem walk of ~/Documents, ~/Desktop and iCloud Drive.", parser="desktop/scripts/demo_library.py", accumulate=False) as w:
        docs = [("Resume - Riley Park.pdf", "Riley Park. Senior Software Engineer. Lumen Labs (Chicago), Fernwood (San Francisco). Python, TypeScript, Postgres."),
                ("Lease - Wicker Flats 3B.pdf", "Residential lease agreement. Unit 3B. Term: 12 months beginning August 1."),
                ("Half marathon plan.numbers", "Week, Tuesday, Thursday, Saturday long run. 12 weeks to race day."),
                ("Lisbon itinerary.pages", "Lisbon and Porto: ten days in May. Alfama, Belém, LX Factory, train to Porto."),
                ("Tokyo budget.numbers", "Flights, hotel in Shibuya, JR pass, food (a lot of ramen)."),
                ("Taxes 2024 notes.txt", "Things to gather: W-2, 1099-INT, moving receipts, charitable donations."),
                ("Wedding toast draft.pages", "Priya, I've known you since our first week of college, when we got lost looking for the library...")]
        for i, (name, text) in enumerate(docs):
            d = TODAY - dt.timedelta(days=R.randint(20, 800))
            w.add(id=f"doc-{i}", kind="document", ts=at(d, 20), author="me", is_me=True, thread="Documents", thread_name="Documents", title=name, text=text,
                  meta={"root": "~/Documents", "path": f"~/Documents/{name}", "bytes": R.randint(20_000, 900_000), "created": at(d, 20)})
    with Writer("chatgpt", "ChatGPT > Settings > Data controls > Export data.", parser="desktop/scripts/demo_library.py", accumulate=False) as w:
        chats = [("Packing list for Tokyo in spring", "What should I pack for Tokyo and Kyoto in late March?", "Layers: it's 8–17°C. A light jacket, comfortable walking shoes, a foldable bag for shopping..."),
                 ("Wedding toast help", "Help me tighten a two-minute wedding toast for my best friend", "Here's a tighter version that keeps your library story and lands the ending..."),
                 ("Chicago winter survival", "I'm moving from SF to Chicago. What do I need for winter?", "A long down coat, waterproof boots, merino layers, and a good hat. Also: embrace it..."),
                 ("Sourdough schedule", "Give me a weekend sourdough schedule", "Friday night: feed the starter. Saturday 9am: mix. Fold every 30 min until 1pm...")]
        for i, (title, q, a) in enumerate(chats):
            d = TODAY - dt.timedelta(days=R.randint(30, 600))
            if "Tokyo" in title:
                d = y(1, "03-01")
            if "Chicago" in title:
                d = y(1, "07-02")
            w.add(id=f"gpt-{i}a", kind="ai_turn", ts=at(d, 20), author="me", is_me=True, thread=f"gpt-{i}", thread_name=title, text=q, meta={"tool": "chatgpt"})
            w.add(id=f"gpt-{i}b", kind="ai_turn", ts=at(d, 20, 1), author="chatgpt", is_me=False, thread=f"gpt-{i}", thread_name=title, text=a, meta={"tool": "chatgpt", "model": "gpt-5"})


def accounts():
    """What the exports from LinkedIn, X and Venmo hold, and the address book."""
    with Writer("contacts", "Local SQLite: ~/Library/Application Support/AddressBook/Sources/*/AddressBook-v22.abcddb.", parser="desktop/scripts/demo_library.py", accumulate=False) as w:
        for i, n in enumerate(CAST):
            w.add(id=f"ct-{i}", kind="contact", ts=at(START + dt.timedelta(days=i * 20), 12), title=n, text=f"{n}\nphone (Mobile): {PHONE[n]}\nemail (home): {EMAIL[n]}",
                  meta={"modified": at(START + dt.timedelta(days=i * 20), 12)})
    with Writer("linkedin", "LinkedIn > Settings > Data privacy > Get a copy of your data.", parser="desktop/scripts/demo_library.py", accumulate=False) as w:
        w.add(id="li-pos-1", kind="position", ts=at(y(5, "02-01"), 9), author="me", is_me=True, title="Software Engineer at Fernwood", text="Software Engineer, Fernwood, San Francisco", meta={"file": "Positions.csv"})
        w.add(id="li-pos-2", kind="position", ts=at(NEW_JOB, 9), author="me", is_me=True, title="Senior Software Engineer at Lumen Labs", text="Senior Software Engineer, Lumen Labs, Chicago", meta={"file": "Positions.csv"})
        for i, n in enumerate(list(CAST)[:25]):
            w.add(id=f"li-c-{i}", kind="contact", ts=at(START + dt.timedelta(days=i * 60), 12), author=n, is_me=False, title=n, text=f"{n}, connected", meta={"file": "Connections.csv"})
        ad_profile_linkedin(w)
    with Writer("x", "X > Settings > Your account > Download an archive of your data.", parser="desktop/scripts/demo_library.py", accumulate=False) as w:
        posts = ["the lake this morning >>>", "first snow in Chicago and I have never been colder or happier", "ran 12 miles and now I'm a different person",
                 "hot take: the best ramen is the one you're eating", "shipped a thing at work today 🚢", "Kyoto at 7am is a different planet",
                 "pastéis de nata should be a food group", "climbing gym at 7am is my therapy"]
        for i in range(60):
            d = START + dt.timedelta(days=R.randrange((TODAY - START).days))
            w.add(id=f"x-{i}", kind="post", ts=at(d, 21), author="me", is_me=True, text=pick(posts), url=f"https://x.com/rileyp/status/{1700000000000 + i}", meta={"likes": R.randint(0, 40)})
        ad_profile_x(w)
    with Writer("phone_venmo", "iPhone backup → iLEAPP → Venmo.", parser="desktop/scripts/demo_library.py", accumulate=False) as w:
        for i in range(300):
            d = START + dt.timedelta(days=R.randrange((TODAY - START).days))
            who = pick(["Maya Chen", "Jordan Reyes", "Sam Okafor", "Priya Patel", "Ruby Walsh", "Theo Laurent"] if d >= MOVE else ["Jordan Reyes", "Sam Okafor", "Maya Chen", "Priya Patel"])
            what = pick(["groceries 🥑", "dinner 🍜", "rent", "concert tickets 🎶", "uber home", "brunch", "gas ⛽", "trivia tab 🍻", "climbing pass"])
            amt = R.randint(8, 95) if what != "rent" else 1250
            w.add(id=f"vm-{i}", kind="transaction", ts=at(d, 20), text=f"{who} paid you ${amt}.00 for {what}" if R.random() < 0.5 else f"You paid {who} ${amt}.00 for {what}",
                  meta={"artifact": "venmo", "category": "Venmo", "fields": {"note": what, "amount": amt}})


# ---------------------------------------------------------------- what advertisers keep about Riley

# Brands Riley deals with (some email them), and a long tail of ones they've never heard of: a made-up mix, the way
# a real list mixes a shop you use with a car dealer three states away.
KNOWN_BRANDS = ["Strava", "Spotify", "United Airlines", "Airbnb", "Amazon", "Uber", "NYT Cooking", "REI Co-op", "Patagonia", "Allbirds",
                "Sweetgreen", "Warby Parker", "Lyft", "Duolingo", "Goodreads", "First Ascent Climbing", "Wicker Flats Leasing", "Lumen Labs"]
BRAND_A = ["Lake", "North", "Blue", "Summit", "Harbor", "Pine", "Golden", "Silver", "Prairie", "Red", "Maple", "Union", "Cedar", "River", "Bright", "Coastal",
           "Midwest", "Pacific", "Urban", "Stone", "Copper", "Iron", "Willow", "Granite", "Evergreen", "Liberty", "Metro", "Sunrise"]
BRAND_B = ["Realty", "Motors", "Fitness", "Dental", "Insurance", "Bank", "Credit Union", "Outfitters", "Coffee", "Mattress Co.", "Pet Supply", "Furniture",
           "Wireless", "Travel", "Apparel", "Home Goods", "Wellness", "Auto Group", "Solar", "Kitchens", "Skincare", "Vision", "Subaru", "Toyota", "Hotels"]
META_CATEGORIES = ["Frequent travelers", "Frequent international travelers", "Lives away from family", "Away from hometown", "Recently moved",
                   "Commuters", "Technology early adopters", "Engaged shoppers", "Close friends of people with birthdays in a month",
                   "Facebook access (mobile): iPhone 16", "Facebook access (mobile): all mobile devices", "Returned from travels 1 week ago",
                   "Owns: iPhone 16", "Primary email domain: example.com", "New job", "Pet owners (all)"]
META_INTERESTS = ["Rock climbing", "Running", "Half marathon", "Ramen", "Japan", "Lisbon", "Board games", "Indie music", "Sourdough", "Chicago Cubs",
                  "Software engineering", "Coffee", "Hiking", "Travel", "Podcasts", "Golf"]
X_INTERESTS = ["Bouldering", "Running", "Marathon training", "Ramen", "Tokyo", "Chicago", "San Francisco", "Japanese Breakfast", "Phoebe Bridgers",
               "Indie rock", "Board games", "Software development", "Python", "TypeScript", "Open source", "Startups", "Climbing gyms", "Coffee",
               "Baking", "Sourdough", "The Bear", "Severance", "Cooking", "Travel", "Portugal", "Hiking", "National parks", "Cycling",
               "Golf", "Cryptocurrency", "NFL", "Fantasy football", "Real estate", "Parenting"]
X_SHOWS = ["The Bear", "Severance", "Shōgun", "Slow Horses", "Hacks", "The Great British Bake Off", "Abbott Elementary"]
LI_TARGETING = {
    "Member Age": ["25 to 34"], "Member Gender": ["Female"], "Years of Experience": ["6 to 7 years"], "Job Seniorities": ["Senior"],
    "Job Functions": ["Engineering"], "Company Size": ["51-200"], "Company Industries": ["Software Development", "Technology, Information and Internet"],
    "Member Traits": ["Frequent Traveler", "Job Seeker", "Open to Education"], "Buyer Groups": ["IT Decision Makers", "Software Buyers"],
    "High Value Audience Segments": ["Tech Professionals", "Early Adopters"], "Standard Audience Segments": ["Outdoor Enthusiasts", "Fitness Enthusiasts", "Commuters"],
    "Member Interests": ["Software Development", "Machine Learning", "Outdoor Recreation", "Running", "Climbing", "Travel", "Cooking", "Personal Finance",
                         "Startups", "Product Management", "Photography", "Music"],
    "Member Skills": ["Python", "TypeScript", "PostgreSQL", "React", "Distributed Systems", "Kubernetes", "API Design", "Code Review", "Mentoring", "Go"],
    "Profile Locations": ["Chicago, Illinois, United States", "San Francisco Bay Area"], "Company Names": ["Lumen Labs", "Fernwood"],
    "Member Schools": ["University of California, Berkeley"], "Degrees": ["Bachelor of Science"], "Fields of Study": ["Computer Science"],
}


def ad_profile_meta():
    """Facebook's and Instagram's ads files, item by item, as connectors/imports.py writes them."""
    places = ["Chicago", "Evanston", "Oak Park", "Naperville", "Milwaukee", "Schaumburg", "Lincoln Park", "Bay Area", "Oakland", "Marin", "Denver", "Austin"]
    known = KNOWN_BRANDS + [f"{a} {b}" for a in BRAND_A for b in BRAND_B] + [f"{p} {b}" for p in places for b in BRAND_B]
    R.shuffle(known)
    names = KNOWN_BRANDS + known[: 1400]
    for site in ("facebook", "instagram"):
        service = site.title()
        with Writer(f"{site}_activity", f"Meta Accounts Center > Download your information ({service}, JSON).", parser="desktop/scripts/demo_library.py", accumulate=False) as w:
            for i, n in enumerate(dict.fromkeys(names)):
                hows = ["list"] if n in KNOWN_BRANDS[:10] or R.random() < 0.34 else []
                if n in KNOWN_BRANDS or R.random() < 0.7 or not hows:
                    hows.append("activity")
                for how in hows:
                    w.add(id=f"{site}-adv-{how}-{i}", kind="advertiser", author=n, is_me=False, title=n,
                          text=f"{service}: {n} {'uploaded a list (its customers, subscribers or contacts) that you were matched to' if how == 'list' else 'matched you from what you did on its website, in its app or in its store'}.",
                          meta={"file": "advertisers_using_your_activity_or_information", "how": how, "service": service})
            for i, c in enumerate(META_CATEGORIES):
                w.add(id=f"{site}-cat-{i}", kind="inference", author=service, is_me=False, title=c, text=f"{service} reaches you with ads under the category “{c}”.",
                      meta={"file": "other_categories_used_to_reach_you", "what": "category", "service": service})
            for i, c in enumerate(META_INTERESTS):
                w.add(id=f"{site}-int-{i}", kind="inference", ts=at(TODAY - dt.timedelta(days=R.randint(5, 300)), 12), author=service, is_me=False, title=c,
                      text=f"{service} interest: {c}", meta={"file": "interest_categories", "what": "interest", "service": service})
            if site == "facebook":
                for i, (company, types) in enumerate([("Strava", ["PAGE_VIEW", "CUSTOM", "SEARCH"]), ("United Airlines", ["SEARCH", "VIEW_CONTENT", "PURCHASE"]),
                                                      ("Airbnb", ["SEARCH", "VIEW_CONTENT", "ADD_TO_WISHLIST", "PURCHASE"]), ("REI Co-op", ["VIEW_CONTENT", "ADD_TO_CART", "PURCHASE"]),
                                                      ("Sweetgreen", ["ACTIVATE_APP", "PURCHASE"]), ("Duolingo", ["ACTIVATE_APP", "CUSTOM"]),
                                                      ("Warby Parker", ["PAGE_VIEW", "ADD_TO_CART"]), ("Lakeshore Realty", ["PAGE_VIEW", "LEAD"]),
                                                      ("Goodreads", ["PAGE_VIEW"]), ("Pacific Mattress Co.", ["PAGE_VIEW", "ADD_TO_CART"])]):
                    events = sorted(({"type": pick(types), "ts": at(TODAY - dt.timedelta(days=R.randint(1, 700)), R.uniform(8, 23))}
                                     for _ in range(R.randint(2, 40))), key=lambda e: e["ts"])
                    events = [e for e in events if e["ts"] <= NOW_ISO]
                    kinds = collections.Counter(e["type"] for e in events)
                    w.add(id=f"offmeta-{i}", kind="off_platform", ts=events[-1]["ts"], author=company, is_me=False, title=company,
                          text=f"{company} told Facebook what you did in its app or on its website: {len(events)} times ("
                               + ", ".join(f"{t.lower().replace('_', ' ')} ×{c}" for t, c in kinds.most_common()) + ").",
                          meta={"file": "your_activity_off_meta_technologies", "service": "Facebook", "events": events})
            else:
                for i in range(420):
                    d = TODAY - dt.timedelta(days=R.randint(0, 540))
                    who = pick(KNOWN_BRANDS[:12] + [f"{pick(BRAND_A)} {pick(BRAND_B)}" for _ in range(6)])
                    w.add(id=f"ig-ad-{i}", kind="ad", ts=at(d, R.uniform(7, 24)), author=who, is_me=False, title=who,
                          text=f"Instagram showed you an ad from {who}: {pick(['New season, new gear', 'Your next trip starts here', 'Members save 20% this week', 'Try it free for 30 days', 'Made for runners', 'Back in stock'])}",
                          meta={"file": "ads_viewed", "service": "Instagram"})


def ad_profile_x(w):
    """X's personalization file, ads with why, and a conversion: what an X export says about Riley."""
    def inf(what, value, text, off=False):
        w.add(id=f"x-inf-{what}-{value}", kind="inference", author="X", is_me=False, title=value, text=text,
              meta={"file": "personalization", "what": what, "service": "X", **({"turned_off": True} if off else {})})
    inf("gender", "female", "X guessed your gender: female")
    inf("age", "25-34", "X guessed your age: 25-34")
    inf("language", "English", "X thinks you speak English")
    inf("location", "Chicago, IL", "X thinks you've been in Chicago, IL")
    inf("audiences", "214 audiences", "Advertisers have put you in 214 audiences on X.")
    for i in X_INTERESTS:
        inf("interest", i, f"X thinks you're interested in {i}", off=i in ("Cryptocurrency", "Parenting"))
    for sh in X_SHOWS:
        inf("show", sh, f"X thinks you watch {sh}")
    for h in ["@Strava", "@united", "@Airbnb", "@REI", "@Spotify", "@Duolingo", "@sweetgreen", "@Patagonia", "@allbirds"]:
        w.add(id=f"x-adv-{h}", kind="advertiser", author=h, is_me=False, title=h, text=f"X: {h} uploaded a list (its customers, subscribers or contacts) that you were matched to.",
              meta={"file": "personalization", "how": "list", "service": "X"})
    for h in ["@nike", "@peloton"]:
        w.add(id=f"x-look-{h}", kind="advertiser", author=h, is_me=False, title=h, text=f"X: {h} aims its ads at people like those on its lists, and you were counted as one.",
              meta={"file": "personalization", "how": "lookalike", "service": "X"})
    for i in range(60):
        d = TODAY - dt.timedelta(days=R.randint(0, 400))
        who, why = pick([("Strava", ["Interests: Running", "Locations: Chicago"]), ("REI Co-op", ["Interests: Hiking", "Age: 25 to 34"]),
                         ("United Airlines", ["Lookalikes: @united", "Locations: Chicago"]), ("Lakeshore Realty", ["Locations: Chicago", "Events: Recently moved"]),
                         ("Peloton", ["Interests: Running", "Gender: female"]), ("Duolingo", ["Keywords: learn portuguese"])])
        w.add(id=f"x-ad-{i}", kind="ad", ts=at(d, R.uniform(8, 23)), author=who, is_me=False, title=who, text=f"X showed you an ad from {who}, because of {'; '.join(why)}.",
              meta={"file": "ad-impressions", "service": "X", "why": why})
    w.add(id="x-conv-1", kind="off_platform", ts=at(TODAY - dt.timedelta(days=33), 19), author="REI Co-op", is_me=False, title="REI Co-op",
          text="REI Co-op told X you visited its site (Mobile).", meta={"file": "ad-online-conversions-attributed", "service": "X", "events": [{"type": "SiteVisit", "ts": at(TODAY - dt.timedelta(days=33), 19)}]})


def ad_profile_linkedin(w):
    for col, values in LI_TARGETING.items():
        for v in values:
            w.add(id=f"li-target-{col}-{v}", kind="inference", author="LinkedIn", is_me=False, title=v, text=f"LinkedIn lets advertisers reach you by {col}: {v}",
                  meta={"file": "ad_targeting.csv", "what": col, "service": "LinkedIn"})
    w.add(id="li-inf-1", kind="inference", author="LinkedIn", is_me=False, title="Affinity for Electric Vehicles", text="LinkedIn inferred this about you: Affinity for Electric Vehicles: yes.",
          meta={"file": "inferences_about_you.csv", "what": "Inferred interests", "service": "LinkedIn"})


def identity():
    (CORPUS / "identity.json").write_text(json.dumps({"names": [ME["name"], "Riley"], "emails": [ME["email"], ME["work"], ME["old_work"]],
                                                      "usernames": [ME["username"]], "phones": [ME["phone"]]}, indent=2))


def home():
    """The made-up home folder: an iPhone backup the library has read, and the settings that keep history."""
    if not ARGS.home:
        return
    h = Path(ARGS.home)
    for d in ("Library/Preferences", "Library/Messages", "Library/Mail", "Downloads", "Documents", ".claude"):
        (h / d).mkdir(parents=True, exist_ok=True)
    (h / "Library/Preferences/com.apple.MobileSMS.plist").write_bytes(plistlib.dumps({"KeepMessageForDays": 0}))
    (h / ".claude/settings.json").write_text(json.dumps({"cleanupPeriodDays": 100000}))
    (h / ".zshrc").write_text("setopt EXTENDED_HISTORY\nHISTSIZE=1000000\nSAVEHIST=1000000\n")
    safari = h / "Library/Containers/com.apple.Safari/Data/Library/Preferences"
    safari.mkdir(parents=True, exist_ok=True)
    (safari / "com.apple.Safari.plist").write_bytes(plistlib.dumps({"HistoryAgeInDaysLimit": 365000}))  # Safari's "Manually"
    when = dt.datetime.combine(TODAY - dt.timedelta(days=1), dt.time(22, 14))
    b = h / "Library/Application Support/MobileSync/Backup/00008130-DEMO0000000000AA"
    b.mkdir(parents=True, exist_ok=True)
    (b / "Info.plist").write_bytes(plistlib.dumps({"Device Name": "Riley's iPhone", "Product Type": "iPhone17,1", "Product Version": "26.0", "Last Backup Date": when}))
    (b / "Manifest.plist").write_bytes(plistlib.dumps({"IsEncrypted": True, "Version": "10.0"}))
    (b / "Status.plist").write_bytes(plistlib.dumps({"SnapshotState": "finished", "Date": when}))
    (b / "Manifest.db").write_bytes(b"")
    raw = CORPUS / "raw/iphone"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "backup.json").write_text(json.dumps({"backup": b.name, "backed_up": (when.astimezone(UTC) if when.tzinfo else when).strftime("%Y-%m-%d %H:%M:%S")}))


def main():
    if CORPUS.exists():
        keep = CORPUS / "files" / "photos"
        for p in CORPUS.iterdir():
            if p != CORPUS / "files":
                shutil.rmtree(p) if p.is_dir() else p.unlink()
        for p in (CORPUS / "files").iterdir() if (CORPUS / "files").exists() else []:
            if p != keep:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
    CORPUS.mkdir(parents=True, exist_ok=True)
    identity()
    home()
    messages()
    calls()
    photos()
    calendar()
    notes_and_reminders()
    email()
    health()
    music()
    browsing()
    made()
    accounts()
    ad_profile_meta()
    import build_index
    build_index.main()


if __name__ == "__main__":
    main()
