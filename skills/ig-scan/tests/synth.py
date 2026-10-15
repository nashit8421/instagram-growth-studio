"""Synthetic account for tests and the demo. Deterministic, no network."""

import datetime as dt
import json
import random

HOOKS = [
    "Nobody tells you your first client contract is the one that hurts",
    "Stop sending invoices without a late fee clause",
    "3 clauses every freelance contract needs",
    "If you freelance, read this before you sign anything",
    "I lost $4,000 because of one missing line in a contract",
    "How do you get clients to pay on time?",
    "Here is my exact contract template for new clients",
    "Freelancers, this is the email I send when a client ghosts",
    "The biggest mistake new freelancers make with pricing",
    "Contract vs handshake: what actually protects you",
]
BODIES = [
    "Freelance contracts protect your rates and your time. Clients respect a clear scope.",
    "Pricing your freelance work is about the client, the scope and the contract terms.",
    "Late invoices kill freelance income. Put payment terms in the contract.",
    "Every client deserves a clear scope. Every freelancer deserves to get paid.",
]
CTAS = ["Comment CONTRACT and I will send you the template.", "Save this for your next client.",
        "Follow for more freelance contract tips.", "", "Link in bio for the full template."]
TAGS = ["#freelance #contracts #freelancetips", "#freelancer #clients", "",
        "#freelance #contracts #invoice #pricing #clients #business #smallbusiness"]


def make_captured(n=40, today=dt.date(2026, 10, 15), followers=18400, seed=7, handle="contractcoach"):
    rnd = random.Random(seed)
    posts = []
    day = today - dt.timedelta(days=1)
    for i in range(n):
        t = ["reel", "reel", "carousel", "photo"][i % 4]
        hook = HOOKS[i % len(HOOKS)]
        caption = "\n\n".join(x for x in (hook, BODIES[i % len(BODIES)], CTAS[i % len(CTAS)],
                                           TAGS[i % len(TAGS)]) if x)
        base = {"reel": 5200, "carousel": 2600, "photo": 900}[t]
        mult = 3.5 if i % 9 == 0 else rnd.uniform(0.5, 1.6)
        views = int(base * mult) if t == "reel" else None
        likes = int(base * mult * 0.06)
        posts.append({"date": day.isoformat(), "type": t, "caption": caption,
                      "likes": likes, "comments": max(1, likes // 12), "views": views,
                      "url": f"https://www.instagram.com/{'reel' if t == 'reel' else 'p'}/C{i:04d}/"})
        day -= dt.timedelta(days=rnd.choice([2, 3, 3, 4, 5, 9]))
    return {"handle": handle, "name": "Contract Coach | Freelance law, plainly",
            "bio": "Freelance contracts without the legalese. Mumbai 🇮🇳", "website": "https://contractcoach.in",
            "followers": followers, "following": 410, "posts_count": 212, "account_type": "creator",
            "category": "Education", "source": "kweo", "posts": posts, "notes": ""}


if __name__ == "__main__":
    print(json.dumps(make_captured(), indent=2, ensure_ascii=False))
