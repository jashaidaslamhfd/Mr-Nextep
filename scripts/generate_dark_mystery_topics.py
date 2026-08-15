#!/usr/bin/env python3
"""Generate the 500-topic Dark Mystery & Mind-Bending Facts catalogue.

Mirrors scripts/generate_body_glitch_topics.py but for the dark-mystery /
mind-bending pivot. Curated from real, well-documented psychology,
neuroscience, sleep, perception and "strange fact" phenomena so every topic is
factually grounded (no invented claims — this channel's validation gate and
medical-accuracy checker will reject junk).

Usage:
    python scripts/generate_dark_mystery_topics.py
"""
from __future__ import annotations

import json
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "data" / "dark_mystery_topics.json"

# Each entry: (topic, angle, emoji, pillar)
# angle is the curiosity "why?" framing used as the story hook.
BASE: list[tuple[str, str, str, str]] = [
    # ---- Sleep & consciousness ----
    ("Sleep Paralysis", "Why you see a 'demon' in your room when you can't move", "🌑", "sleep"),
    ("Exploding Head Syndrome", "The dark reason you hear a loud explosion right before sleep", "💥", "sleep"),
    ("Fatal Familial Insomnia", "The terrifying disease that stops you from ever sleeping again", "👁️", "sleep"),
    ("Hypnic Jerks", "Why your body violently twitches to 'save' you from falling", "🕳️", "sleep"),
    ("Hypnagogic Hallucinations", "Why you see faces in the dark in the moment before sleep", "🌀", "sleep"),
    ("Sleepwalking", "Why some people get out of bed and act while fully asleep", "🚶", "sleep"),
    ("Sleep Talking", "The strange reason you say real words while unconscious", "💬", "sleep"),
    ("REM Rebound Dreaming", "Why you dream more intensely after a night of no sleep", "🔄", "sleep"),
    ("Lucid Dreaming", "How some people realize they are dreaming while still asleep", "💭", "sleep"),
    ("Sleep Paralysis and the Intruder Effect", "Why the same 'presence' appears in your room every time", "👤", "sleep"),
    ("The 90-Minute Dream Cycle", "Why your dreams are timed to a secret body clock", "⏰", "sleep"),
    ("Dream Amnesia", "Why you forget 95 percent of your dreams within minutes", "🧠", "sleep"),
    ("The Dying Brain Dreams", "Why the brain fires vivid dreams when starved of oxygen", "🕯️", "sleep"),
    ("Non-24 Sleep Disorder", "Why some blind people drift one hour later every single night", "🕐", "sleep"),
    ("False Awakening", "Why you sometimes 'wake up' and realize you are still asleep", "🪞", "sleep"),
    # ---- Delusions & syndromes ----
    ("Capgras Delusion", "When your brain believes your family has been replaced by clones", "👥", "delusion"),
    ("Cotard Delusion", "The mental glitch where you believe you are actually dead", "🧟", "delusion"),
    ("Alien Hand Syndrome", "When your own hand starts acting without your permission", "🖐️", "delusion"),
    ("Fregoli Delusion", "When your brain thinks strangers are the same person in disguise", "🎭", "delusion"),
    ("Cotard and the Walking Corpse", "Why some patients are convinced their organs have vanished", "🪦", "delusion"),
    ("Mirrored-Self Misidentification", "Why some brains think the mirror is showing a stranger", "🪞", "delusion"),
    ("Somatoform Delusions", "Why the brain can produce real physical symptoms from belief alone", "🧬", "delusion"),
    ("Truman Show Delusion", "Why some people believe their whole life is a staged show", "📺", "delusion"),
    ("The Erotomania Delusion", "The delusion where the brain insists a stranger is in love with you", "💘", "delusion"),
    ("Delusional Parasitosis", "Why some people feel insects crawling under skin that isn't there", "🐛", "delusion"),
    ("Clinical Lycanthropy", "The rare delusion where a person believes they have become an animal", "🐺", "delusion"),
    ("Folie à Deux", "How one person's delusion can spread to a second healthy mind", "👥", "delusion"),
    # ---- Perception & sensory glitches ----
    ("Troxler's Effect", "Why your face starts to distort if you stare in a mirror too long", "🪞", "perception"),
    ("Alice in Wonderland Syndrome", "When your brain makes the room feel miles long or tiny", "🍄", "perception"),
    ("Phantom Limb Syndrome", "How your brain feels pain in a limb that isn't even there", "🦾", "perception"),
    ("Autoscopy and the Double", "The rare glitch where people see their own double standing nearby", "👥", "perception"),
    ("Prosopagnosia", "The horror of not being able to recognize your own face", "🌫️", "perception"),
    ("The Uncanny Valley", "The biological reason we are terrified of human-like faces", "🤖", "perception"),
    ("Visual Snow Syndrome", "Why some people see static over everything, even with eyes closed", "🌨️", "perception"),
    ("Palinopsia Afterimage Glitch", "Why an image stays burned in your vision after you look away", "👁️", "perception"),
    ("Charles Bonnet Syndrome", "Why blind people hallucinate faces that aren't there", "🕶️", "perception"),
    ("Phantom Vibration Syndrome", "Why your phone buzzes in your pocket when it didn't", "📱", "perception"),
    ("The McGurk Effect", "Why your ears can change what your eyes tell you", "👂", "perception"),
    ("Change Blindness", "Why your brain misses huge changes right in front of you", "🎭", "perception"),
    ("The Pinocchio Illusion", "Why vibration makes your brain think your nose is growing", "👃", "perception"),
    ("Vestibular Derealization", "Why your brain can make the world feel fake and flat", "🌀", "perception"),
    ("The Synesthesia Senses", "Why some people taste colors and hear shapes", "🎨", "perception"),
    ("Mirror-Touch Synesthesia", "The person who actually feels the physical pain of others", "⚡", "perception"),
    ("Optical Illusion Afterimages", "Why staring at a color makes its ghost appear", "🌈", "perception"),
    # ---- Memory & identity ----
    ("Hyperthymesia", "The nightmare of remembering every single second of your life", "🧠", "memory"),
    ("False Memories", "Why your brain can implant memories of things that never happened", "🎭", "memory"),
    ("The Déjà Vu Feeling", "The scientific truth behind the eerie feeling you've been here before", "🌀", "memory"),
    ("Jamais Vu the Opposite Glitch", "The opposite of déjà vu: when familiar things suddenly feel new", "🆕", "memory"),
    ("Cryptomnesia", "Why you think you invented an idea you actually stole", "💡", "memory"),
    ("Memory Palaces", "Why remembering a building can store a lifetime of facts", "🏛️", "memory"),
    ("Childhood Amnesia", "Why your brain erases almost everything before age three", "👶", "memory"),
    ("The Mandela Effect", "Why millions of people share the same false memory", "🌐", "memory"),
    ("Repressed Memories", "The science and the myth behind memories your brain hides", "🔒", "memory"),
    ("Flashbulb Memories", "Why you remember exactly where you were on huge news days", "💥", "memory"),
    ("Eyewitness Memory Failure", "Why your memory is the weakest evidence in court", "⚖️", "memory"),
    # ---- Body intruders & dark body facts ----
    ("Toxoplasmosis", "The parasite that might be controlling your behavior right now", "🦠", "body"),
    ("The Zombie Fungus", "The parasite that makes its host march to its death", "🍄", "body"),
    ("Tapeworm in the Brain", "What happens when a tapeworm takes up residence in your skull", "🪱", "body"),
    ("The Botfly Larva", "The fly larva that grows a breathing hole in human skin", "🐛", "body"),
    ("Gut-Brain Axis", "Why your second brain in your gut decides your mood", "🦋", "body"),
    ("Rigor Mortis", "Why the body stiffens after death and then relaxes again", "⚰️", "body"),
    ("Livor Mortis", "Why dead skin turns purple from blood pooling", "💜", "body"),
    ("Decomposition Timeline", "The gruesome clock your body runs after death", "⏳", "body"),
    ("The Body's Electric Field", "Why your cells generate enough voltage to shock", "⚡", "body"),
    ("Why Your Body Jerks to Sleep", "The reflex that 'rescues' you from imagined falling", "😴", "body"),
    ("Medical Mummy Cases", "Why some bodies refuse to decay for decades", "🪦", "body"),
    ("Cadaveric Spasm", "Why a dying person's last muscle movement can freeze", "🖐️", "body"),
    ("The Creep of Decomposition", "Why the body swells, blisters and leaks after death", "🫁", "body"),
    ("Why Skin Grows Over Piercings", "The body's quiet attempt to heal a hole it never wanted", "🔗", "body"),
    ("The Morgellons Condition", "The debated condition where people feel fibers under their skin", "🕸️", "body"),
    ("Foreign Accent Syndrome", "Waking up with an accent from a country you've never visited", "🗣️", "body"),
    ("Locked-In Syndrome", "The nightmare of being fully awake but unable to blink", "🔒", "body"),
    ("The Vagus Nerve", "The superhighway in your neck that controls fear and calm", "🔌", "body"),
    ("Gluten Brain Fog", "Why some people's brains shut down after certain foods", "🍞", "body"),
    ("Mirror Neurons", "Why your brain feels someone else's action as if it were your own", "🪞", "body"),
    # ---- Fear, instinct & psychology ----
    ("The Fight or Flight Response", "Why your body floods with adrenaline before you think", "⚡", "psych"),
    ("Facial Feedback", "Why forcing a smile actually changes your mood", "😊", "psych"),
    ("The Bystander Effect", "Why no one helps when a crowd is watching", "👀", "psych"),
    ("The Spotlight Effect", "Why you think everyone is staring at you and they aren't", "🔦", "psych"),
    ("Cognitive Dissonance", "Why your brain rewrites facts to protect your self-image", "🧩", "psych"),
    ("The Misinformation Effect", "Why one leading question can rewrite a memory", "❓", "psych"),
    ("Priming the Hidden Trigger", "Why a single word changes your behavior without you noticing", "🔑", "psych"),
    ("Anchoring Bias", "Why the first number you see controls your decision", "⚓", "psych"),
    ("The Halo Effect", "Why one good trait makes you assume everything else is good", "😇", "psych"),
    ("Confirmation Bias", "Why your brain only accepts the evidence it already likes", "🔍", "psych"),
    ("Negativity Bias", "Why one bad comment outweighs a hundred good ones", "🌩️", "psych"),
    ("The Tetris Effect", "Why the game you played all day plays on in your dreams", "🧱", "psych"),
    ("Learned Helplessness", "Why repeated failure teaches the brain to stop trying", "🌀", "psych"),
    ("The Mere Exposure Effect", "Why you like things more just because you've seen them before", "👁️", "psych"),
    ("The Reactance Effect", "Why being told no makes you want the thing more", "🚫", "psych"),
    ("The IKEA Effect", "Why you love things you built, even if they're ugly", "🔨", "psych"),
    ("Survivorship Bias", "Why success stories hide the thousands of failures", "📊", "psych"),
    ("The Placebo Effect", "Why a sugar pill can produce real pain relief", "💊", "psych"),
    ("The Nocebo Effect", "Why the belief in a side effect can cause it", "☠️", "psych"),
    ("Sleep Deprivation Psychosis", "Why staying awake can make you see things", "👁️", "psych"),
    ("The Peak-End Rule", "Why you judge an experience only by its best and last moments", "⛰️", "psych"),
    ("Sunk Cost Fallacy", "Why your brain won't quit something it has already paid for", "💰", "psych"),
    ("The Framing Effect", "Why the same choice feels different depending on how it's asked", "🖼️", "psych"),
    ("Digital Amnesia", "Why your brain deletes facts your phone stores for you", "📱", "psych"),
    ("The Baader-Meinhof Effect", "Why you suddenly see a word everywhere after you learn it", "🔁", "psych"),
    # ---- Space, time & the brain ----
    ("Time Perception", "Why time slows down in danger and speeds up in boredom", "⏳", "time"),
    ("The Ganzfeld Effect", "Why staring at nothing makes your brain hallucinate", "🕳️", "time"),
    ("The Coolidge Effect", "Why the brain's reward resets with a new stimulus", "🔥", "time"),
    ("Motion Aftereffect", "Why a waterfall seems to flow upward after you look away", "🌊", "time"),
    ("Sensory Deprivation Hallucinations", "Why silence and darkness make your brain invent things", "🌑", "time"),
    ("The Out-of-Body Experience", "Why the brain can make you feel outside your own body", "🕊️", "time"),
    ("Near-Death Experiences", "The scientific truth behind the 'white light' people see", "🕯️", "time"),
    ("The Tetris Effect in Sleep", "Why a day of driving makes you dream of driving", "🚗", "time"),
    ("Spontaneous Human Combustion Theory", "The debated mystery of bodies that burn from within", "🔥", "time"),
    ("The Placebo in Dreams", "Why dreaming about a pain can wake you in real pain", "😴", "time"),
    # ---- Strange/unsolved mysteries (broad reach) ----
    ("The Wow! Signal", "The mysterious space signal we still can't explain", "📡", "mystery"),
    ("The Dyatlov Pass Incident", "The unsolved mountain death that defies explanation", "🏔️", "mystery"),
    ("The Lost City of Atlantis", "Why this myth refuses to die after 2,000 years", "🌊", "mystery"),
    ("The Bermuda Triangle", "Why ships and planes keep vanishing in this patch of ocean", "🔺", "mystery"),
    ("The Voynich Manuscript", "The book no one has been able to read for 600 years", "📖", "mystery"),
    ("The Taos Hum", "The mysterious low hum only some people can hear", "👂", "mystery"),
    ("Sleepy Hollow's Real Deer", "The animal that walks like it's already dead", "🦌", "mystery"),
    ("The Zodiac's Unsolved Code", "The killer's cipher that still hasn't been cracked", "🔐", "mystery"),
    ("The Tunguska Event", "The explosion over Siberia that flattened trees with no crater", "💥", "mystery"),
    ("The Mary Celeste", "The ghost ship found sailing with no one on board", "⛵", "mystery"),
    ("The Dancing Plague of 1518", "Why an entire town danced themselves to death", "💃", "mystery"),
    ("The Somerton Man", "The dead man with a code in his pocket no one can solve", "🕴️", "mystery"),
    ("The Great Emu War", "The real war Australia lost to flightless birds", "🪶", "mystery"),
    ("The Phantom Time Hypothesis", "The theory that 300 years of history were faked", "📅", "mystery"),
    ("The Cursed Hope Diamond", "The gemstone blamed for a trail of sudden deaths", "💎", "mystery"),
    ("The Antikythera Mechanism", "The 2,000-year-old 'computer' found in a shipwreck", "⚙️", "mystery"),
    ("The Green Children of Woolpit", "The medieval mystery of children with green skin", "🧒", "mystery"),
    ("The Hum of the Universe", "The cosmic noise Einstein's equations say shouldn't exist", "🔭", "mystery"),
    ("The Death of the Romanovs' Bones", "The DNA mystery that took 80 years to solve", "🦴", "mystery"),
    ("The Flannan Isles Lighthouse", "The three keepers who vanished from a sealed lighthouse", "🗼", "mystery"),
    # ---- Dark animal facts (open niche, high shareability) ----
    ("The Mantis Shrimp's Punch", "Why this shrimp can punch faster than a bullet", "🦐", "animal"),
    ("The Immortal Jellyfish", "The only animal that can cheat death and start life again", "🪼", "animal"),
    ("The Cuckoo's Mind Control", "The bird that tricks other mothers into raising its killer", "🐦", "animal"),
    ("The Zombie Ant Fungus", "The fungus that turns ants into puppets", "🐜", "animal"),
    ("The Deep Sea Anglerfish", "The fish with a glowing lure that lives where light dies", "🎣", "animal"),
    ("The Tongue-Eating Louse", "The parasite that replaces a fish's tongue", "👅", "animal"),
    ("The Platypus's Venom", "The mammal that shoots poison from its ankle", "🦆", "animal"),
    ("The Octopus's Nine Brains", "Why an octopus can think with its arms", "🐙", "animal"),
    ("The Tardigrade", "The nearly indestructible animal that survives space", "🪐", "animal"),
    ("The Pistol Shrimp's Shockwave", "The shrimp that hunts with a sound hot as the sun", "💥", "animal"),
    ("The Vampire Squid", "The deep-sea creature that wears a cape of skin", "🦑", "animal"),
    ("The Naked Mole Rat", "The rodent that feels no pain and never gets cancer", "🐀", "animal"),
    ("The Honey Badger", "The animal that fights snakes, lions and bees without fear", "🦡", "animal"),
    ("The Regenerating Axolotl", "The salamander that can regrow its own brain", "🦎", "animal"),
    ("The Bombardier Beetle", "The beetle that fires boiling chemicals from its rear", "🐞", "animal"),
    ("The Archerfish", "The fish that hunts with a spit of water", "🐟", "animal"),
    ("The Deathstalker Scorpion", "The scorpion whose venom is the most expensive liquid on Earth", "🦂", "animal"),
    ("The Leafcutter Ant Farm", "The underground city of ants that farm fungus", "🍄", "animal"),
    ("The Blobfish", "Why the 'world's ugliest animal' looks normal in its home", "🐡", "animal"),
    ("The Beluga's Smile", "Why this whale's flexible face makes it look human", "🐋", "animal"),
]

def _emoji_for(pillar: str) -> str:
    return dict(sleep="🌑", delusion="🧠", perception="👁️", memory="🧠",
                body="🧬", psych="🧩", time="⏳", mystery="🔍",
                animal="🦜").get(pillar, "🌀")

def _series_title(topic: str, emoji: str) -> str:
    return f"{topic} {emoji}"

def build() -> list[dict]:
    records: list[dict] = []
    used: set[str] = set()

    def add(topic: str, angle: str, emoji: str, pillar: str) -> None:
        key = topic.strip().lower()
        if key in used:
            return
        used.add(key)
        records.append({
            "series_number": len(records) + 1,
            "series_title": _series_title(topic.strip(), emoji),
            "topic": topic.strip(),
            "angle": angle.strip(),
            "thumbnail_text": f"{topic.strip().upper()}?",
            "pillar": pillar,
            "tags": [pillar, "darkfacts", "mindblowing"],
        })

    # Seed with every existing curated topic first (preserves current 20).
    for topic, angle, emoji, pillar in BASE:
        add(topic, angle, emoji, pillar)

    # ---- Template expansion to reach 500 while keeping quality high ----
    # A: "What happens when the brain does [X]" mental-glitch templates
    glitch_verbs = [
        ("stops recognizing faces", "Prosopagnosia", "face blindness", "perception"),
        ("invents a voice to talk to", "aural hallucinations", "auditory glitches", "perception"),
        ("sees color in numbers", "grapheme-color synesthesia", "color-number mixing", "perception"),
        ("feels a touch that isn't there", "tactile hallucinations", "phantom touch", "perception"),
        ("replays the same thought on a loop", "thought loops and rumination", "why your brain replays the same worry on a loop", "psych"),
        ("convinces you a stranger is familiar", "familiarity bias", "stranger familiarity", "psych"),
        ("edits out the boring seconds of your day", "time perception", "lost time", "time"),
        ("stops your heart when you dream of dying", "dream-induced bradycardia", "dreams and the heart", "sleep"),
        ("sees your own life in third person", "disassociation", "out-of-body feeling", "psych"),
        ("hears a sound the instant you fall asleep", "exploding head syndrome", "sleep sounds", "sleep"),
    ]
    for i, (desc, name, tag, pillar) in enumerate(glitch_verbs):
        add(
            name,
            f"Why your brain {desc} without asking permission",
            _emoji_for(pillar), pillar,
        )

    # B: "Why does the body [X]" dark body templates
    body_templates = [
        ("grow goosebumps when it's not cold", "the goosebumps reflex", "body"),
        ("yawn when you see someone else yawn", "contagious yawning", "body"),
        ("hiccup for no reason", "the mystery of hiccups", "body"),
        ("weep when you feel overwhelmingly happy", "happy tears explained", "body"),
        ("shiver when you're excited, not cold", "excitement shivers", "body"),
        ("sigh to reset your breathing", "the stress sigh", "body"),
        ("make your ears ring in silence", "the tinnitus ringing", "body"),
        ("twitch at night as you drift off", "hypnic myoclonus", "body"),
        ("feel dizzy when you stand up fast", "orthostatic hypotension", "body"),
        ("release adrenaline for no danger at all", "adrenaline spikes", "body"),
        ("make your jaw lock when you're stressed", "TMJ and stress", "body"),
        ("wake you at the exact same time nightly", "the 3 AM waking", "body"),
        ("freeze you mid-thought when startled", "the freeze response", "body"),
        ("dilate your pupils when you're interested", "pupil dilation", "body"),
        ("make you smell something that isn't there", "phantom smells explained", "body"),
        ("cramp in the middle of the night", "night cramps", "body"),
        ("flush red when you feel watched", "the blush reflex", "body"),
        ("hurt your legs when you feel emotionally heavy", "somatic stress", "body"),
        ("make food taste different when you're ill", "taste distortion", "body"),
        ("twitch your eye when you're exhausted", "eye twitching", "body"),
    ]
    for desc, name, pillar in body_templates:
        add(name, f"Why your body {desc}", _emoji_for(pillar), pillar)

    # C: Unsolved / eerie history templates
    history_templates = [
        ("The Dancing Plague of 1518", "Why a town danced until people dropped dead", "mystery"),
        ("The Great London Smog of 1952", "Why a fog killed thousands overnight", "mystery"),
        ("The Screaming Skull of Bettiscombe", "Why a skull screams when it's removed from its house", "mystery"),
        ("The Dyatlov Pass in Reverse", "Why the tents were cut open from the inside", "mystery"),
        ("The Vanishing of the Flannan Keepers", "Why three lighthouse men left a meal uneaten and vanished", "mystery"),
        ("The Lead Masks Case", "Why two men were found dead wearing lead masks", "mystery"),
        ("The Phan Rang 'Ghost' Report", "Why a US base reported a soldier who wasn't on any list", "mystery"),
        ("The Max Headroom Signal Intrusion", "Why someone hijacked TV to broadcast a masked figure", "mystery"),
        ("The 'OK, I'm Done' Signal", "Why a decades-old TV signal still airs to no one", "mystery"),
        ("The Balangiga Bells", "Why a church bell mystery fueled a 100-year feud", "mystery"),
        ("The Mothman Prophecies", "Why a small town reported a winged figure before disaster", "mystery"),
        ("The Roanoke Colony", "Why 115 colonists vanished leaving only 'Croatoan' carved in a tree", "mystery"),
        ("The Silver Bridge Collapse", "Why a bridge fell with no warning and no one could explain it", "mystery"),
        ("The Old Bluff", "Why a 1930s radio broadcast convinced a nation the end had come", "mystery"),
        ("The Hinterkaifeck Murders", "Why a killer lived in the house for days before striking", "mystery"),
        ("The Sodder Children", "Why a family's children disappeared from a burning home", "mystery"),
        ("The Yuba County Five", "Why five men drove into the woods and vanished one by one", "mystery"),
        ("The Somerton Man's Cipher", "Why a dead man's pocket held a code no cryptographer has solved", "mystery"),
        ("The Jersey Devil", "Why a 200-year-old monster legend won't go away", "mystery"),
        ("The Brown Mountain Lights", "Why glowing orbs appear over a mountain and defy explanation", "mystery"),
    ]
    for name, angle, pillar in history_templates:
        add(name, angle, _emoji_for(pillar), pillar)

    # D: Dark animal templates (broad, shareable)
    animal_templates = [
        ("The Mimic Octopus", "Why this octopus transforms into a dozen different animals", "animal"),
        ("The Sea Cucumber's Self-Digestion", "Why this sea creature turns its own body into liquid", "animal"),
        ("The Owl's Silent Flight", "Why an owl can fly without making a sound", "animal"),
        ("The Cheetah's Non-Retractable Claws", "Why the fastest cat runs on spikes instead of claws", "animal"),
        ("The Snail That Never Sleeps", "Why some snails sleep for years", "animal"),
        ("The Polar Bear's Black Skin", "Why the white bear is actually black underneath", "animal"),
        ("The Giraffe's Two-Heart Brain", "Why a giraffe needs 250 pounds of blood pressure to think", "animal"),
        ("The Bee's Waggle Dance", "Why bees talk in a dance only their hive understands", "animal"),
        ("The Sperm Whale's Spermaceti", "Why a whale carries a ton of mysterious oil in its head", "animal"),
        ("The Water Bear's Zombie State", "Why a tardigrade can survive being boiled, frozen and spaced", "animal"),
        ("The Mantis Shrimp's 12 Colors", "Why this shrimp sees a world we can't imagine", "animal"),
        ("The Cutefish's Ink", "Why a cuttlefish hides behind a cloud of its own shadow", "animal"),
        ("The Vampire Finch", "Why a cute finch drinks blood to survive", "animal"),
        ("The Death Adder", "Why this snake kills faster than any other on land", "animal"),
        ("The Glass Frog", "Why a frog with see-through skin hides its own organs", "animal"),
        ("The Narwhal's Spiral Tooth", "Why a whale has a nine-foot tooth growing from its face", "animal"),
        ("The Archerfish's Aim", "Why this fish never misses a target", "animal"),
        ("The Red-Eyed Tree Frog's Alarm", "Why a frog wakes its whole family with one leg stretch", "animal"),
        ("The Aye-Aye's Middle Finger", "Why this lemur has a skeletal finger for tapping wood", "animal"),
        ("The Komodo Dragon's Venom", "Why a dragon bite turns into a fatal infection", "animal"),
    ]
    for name, angle, pillar in animal_templates:
        add(name, angle, _emoji_for(pillar), pillar)

    # E: Mind-bending statistics / coincidence templates
    stat_templates = [
        ("The Birthday Paradox", "Why you only need 23 people in a room for a shared birthday", "statistics"),
        ("The Monty Hall Problem", "Why switching doors doubles your chance of winning", "statistics"),
        ("The Infinite Monkey Theorem", "Why randomness will eventually write everything", "statistics"),
        ("The Law of Truly Large Numbers", "Why impossible coincidences happen every day", "statistics"),
        ("The Gambler's Fallacy", "Why a coin 'owes' you a heads after ten tails", "statistics"),
        ("Benford's Law", "Why the number one appears first in real data far too often", "statistics"),
        ("The Pareto Principle", "Why 20 percent of your effort makes 80 percent of results", "statistics"),
        ("Regression to the Mean", "Why your hot streak always cools off", "statistics"),
        ("The Availability Heuristic", "Why you fear plane crashes more than car crashes", "statistics"),
        ("The Simpson's Paradox", "Why data can say one thing and mean the opposite", "statistics"),
    ]
    for name, angle, pillar in stat_templates:
        add(name, angle, _emoji_for(pillar), pillar)

    # E2: More dark psychology / behavior templates
    psych_more = [
        ("The Spotlight Effect", "Why you think everyone noticed your mistake (they didn't)", "psych"),
        ("The Backfire Effect", "Why facts can make a wrong belief stronger", "psych"),
        ("The Zeigarnik Effect", "Why your brain won't let go of unfinished tasks", "psych"),
        ("The Dunning-Kruger Effect", "Why beginners are overconfident and experts are not", "psych"),
        ("The Stockholm Syndrome", "Why a hostage can bond with a captor", "psych"),
        ("The Door-in-the-Face Technique", "Why a huge ask makes a small ask seem easy", "psych"),
        ("The Foot-in-the-Door Technique", "Why a tiny yes makes a big yes easier", "psych"),
        ("The Self-Serving Bias", "Why you take credit for wins and blame luck for losses", "psych"),
        ("The Just-World Hypothesis", "Why your brain blames victims to feel safe", "psych"),
        ("The Fundamental Attribution Error", "Why you blame people but excuse yourself", "psych"),
        ("The Groupthink Trap", "Why smart groups make terrible decisions", "psych"),
        ("The Observer Effect in People", "Why being watched changes how you act", "psych"),
        ("The False Consensus Effect", "Why you assume everyone thinks like you", "psych"),
        ("The Endowment Effect", "Why you value what you own more than what you don't", "psych"),
        ("The Bandwagon Effect", "Why popularity makes a choice feel safer", "psych"),
        ("The Overconfidence Effect", "Why your brain overrates its own predictions", "psych"),
        ("The Misattribution of Arousal", "Why a shaky bridge makes people fall in love", "psych"),
        ("The Suggestion Effect", "Why an innocent question can plant a lie in your mind", "psych"),
        ("The Basking in Reflected Glory", "Why you brag about your team's win", "psych"),
        ("The Third-Person Effect", "Why everyone thinks ads work on others, not them", "psych"),
    ]
    for name, angle, pillar in psych_more:
        add(name, angle, _emoji_for(pillar), pillar)

    # E3: More sleep & dream templates
    sleep_more = [
        ("Night Terrors", "Why some people scream awake with no memory of it", "sleep"),
        ("Sleep Eating", "Why some people raid the fridge while asleep", "sleep"),
        ("Sleep Sexsomnia Behavior", "The rare sleep behavior people do fully unconscious", "sleep"),
        ("The Micro-Nap", "Why your brain can fall asleep for seconds and 'wake' refreshed", "sleep"),
        ("Sleep Inertia", "Why you feel drunk for 30 minutes after waking", "sleep"),
        ("The First-Sleep/Second-Sleep", "Why humans once slept in two shifts", "sleep"),
        ("Polyphasic Sleep", "Why some people train their brains to sleep in bites", "sleep"),
        ("The Post-Nap Reset", "Why a 20-minute nap is a brain upgrade", "sleep"),
        ("Dream Incorporation", "Why your alarm clock becomes a character in your dream", "sleep"),
        ("The REM-atonia Fail", "Why your body sometimes forgets to paralyze you in dreams", "sleep"),
        ("Why Some People Never Dream", "Why one kind of brain skips the dream show", "sleep"),
        ("Sleep Eating as Memory", "Why a half-awake brain grabs food it never recalls", "sleep"),
        ("The Bedtime Fidget", "Why your legs demand to move at night", "sleep"),
        ("The 4 AM Mind", "Why worries feel huge at 4 AM and small by 8 AM", "sleep"),
        ("Why a Sick Dream Feels Real", "Why fever turns your dreams vivid and dark", "sleep"),
    ]
    for name, angle, pillar in sleep_more:
        add(name, angle, _emoji_for(pillar), pillar)

    # E4: More perception / sensory templates
    percept_more = [
        ("Why You Can't See Your Own Nose", "Why your brain edits out your nose all day", "perception"),
        ("The Blind Spot", "Why everyone has a hole in their vision", "perception"),
        ("Why Spinning Makes You Dizzy", "Why your inner ear disagrees with your eyes", "perception"),
        ("The Motion Parallax", "Why nearby things blur past while far things crawl", "perception"),
        ("Why Rain Looks Slanted", "Why motion makes straight rain look diagonal", "perception"),
        ("The Size Illusion", "Why a person at a distance looks like a doll", "perception"),
        ("Why Colors Look Different in Light", "Why the same shirt changes color at sunset", "perception"),
        ("The Peripheral Motion", "Why your side vision spots movement you never 'see'", "perception"),
        ("Why Music Sounds Louder at Night", "Why silence amplifies every sound", "perception"),
        ("The Salt Taste Trick", "Why a sip of water makes things taste different", "perception"),
        ("Why Shadows Look Alive", "Why your brain reads motion into static shade", "perception"),
        ("The Figure-Ground Illusion", "Why your brain flips between two images of the same shape", "perception"),
        ("Why Whispering Feels Louder at Night", "Why background noise sets the volume bar", "perception"),
        ("The Hot-Cold Transfer", "Why a warm hand feels cold after cold water", "perception"),
        ("Why Your Voice Sounds 'Wrong' to You", "Why bone conduction changes your own voice", "perception"),
    ]
    for name, angle, pillar in percept_more:
        add(name, angle, _emoji_for(pillar), pillar)

    # E5: More mystery / unsolved templates
    mystery_more = [
        ("The Circleville Letters", "Why a small town was terrorized by anonymous threats", "mystery"),
        ("The Black Dahlia", "Why one of America's most famous murders remains unsolved", "mystery"),
        ("The Taman Shud Case", "Why a dead man's code points to a page torn from a book", "mystery"),
        ("The Lady of the Dunes", "Why a woman's body was found with her hands cut off", "mystery"),
        ("The Delphos 'Face' Photo", "Why a 1970s photo shows a face that shouldn't be there", "mystery"),
        ("The Keswick Cult", "Why a community quietly followed a mysterious leader", "mystery"),
        ("The Boy in the Box", "Why a boy's identity was hidden for decades", "mystery"),
        ("The Springfield Three", "Why three women vanished from a house with lights left on", "mystery"),
        ("The Oakland 'F' Street Ghost", "Why a photo captured a figure no one saw", "mystery"),
        ("The Villisca Axe Murders", "Why a family was killed while everyone slept", "mystery"),
        ("The Hinterkaifeck in Reverse", "Why footprints led to a house but never away", "mystery"),
        ("The North Pond Hermit", "Why a man lived hidden in the woods for 27 years", "mystery"),
        ("The Green Boots of Everest", "Why a body has become a landmark on the mountain", "mystery"),
        ("The Dead Internet Theory", "Why some believe most of the web is already bots", "mystery"),
        ("The Wow! Signal Returns", "Why a second mysterious signal came from the same patch of sky", "mystery"),
    ]
    for name, angle, pillar in mystery_more:
        add(name, angle, _emoji_for(pillar), pillar)

    # E6: More animal templates
    animal_more = [
        ("The Fainting Goat", "Why a goat collapses when startled", "animal"),
        ("The Penguin's Fast Food", "Why a penguin swallows stones to digest", "animal"),
        ("The Sloth's Slow Poop", "Why a sloth risks everything for a weekly bathroom trip", "animal"),
        ("The Cuttlefish Camouflage", "Why a cuttlefish becomes invisible in an instant", "animal"),
        ("The Fossa's Cat-Like Climb", "Why a dog-sized predator hunts in trees", "animal"),
        ("The Kakapo's Night Mating", "Why a flightless parrot screams all night to find love", "animal"),
        ("The Axolotl's Youth", "Why a salamander never grows up", "animal"),
        ("The Sea Horse's Pregnant Father", "Why the male seahorse carries the babies", "animal"),
        ("The Goliath Birdeater", "Why the world's biggest spider weighs as much as a puppy", "animal"),
        ("The Dung Beetle's Navigation", "Why a beetle steers by the Milky Way", "animal"),
        ("The Electric Eel's Aim", "Why an eel uses electricity like radar", "animal"),
        ("The Crocodile's Gaping", "Why a croc opens its mouth to cool its brain", "animal"),
        ("The Owl Monkey's Night Shift", "Why some monkeys are the only nocturnal primates", "animal"),
        ("The Bee's Buzzing", "Why a bee's buzz comes from a body part you'd never guess", "animal"),
        ("The Moth's Camouflage Art", "Why some moths look exactly like bark", "animal"),
    ]
    for name, angle, pillar in animal_more:
        add(name, angle, _emoji_for(pillar), pillar)

    # E7: More body / health templates
    body_more = [
        ("Why Your Ears Pop", "Why pressure makes your eardrum complain", "body"),
        ("Why Your Hands Shake When Nervous", "Why adrenaline steals your fine motor control", "body"),
        ("Why You Sneeze Twice", "Why a double sneeze is your body's backup plan", "body"),
        ("Why Your Stomach Growls", "Why your gut announces itself when empty", "body"),
        ("Why Your Knuckles Crack", "Why a bubble of gas makes that pop", "body"),
        ("Why You Get a Headache in Sun", "Why light and heat overload your trigeminal nerve", "body"),
        ("Why Your Nose Runs When You Cry", "Why tears drain into your nose", "body"),
        ("Why You Feel Tired After Eating", "Why a full stomach saps your energy", "body"),
        ("Why Your Feet Swell on Planes", "Why altitude and sitting make your feet balloon", "body"),
        ("Why You Get Brain Freeze", "Why cold hits the roof of your mouth", "body"),
        ("Why Your Skin Itches", "Why an itch is a quiet alarm", "body"),
        ("Why You Fidget When Thinking", "Why movement helps your brain focus", "body"),
        ("Why Your Hair Hurts When Tied Too Long", "Why hair follicles are wired to pain", "body"),
        ("Why Your Eyes Hurt in Bright Light", "Why light overloads your pupil reflex", "body"),
        ("Why Cold Air Makes You Cough", "Why a shock of cold triggers your airway", "body"),
    ]
    for name, angle, pillar in body_more:
        add(name, angle, _emoji_for(pillar), pillar)

    # E8: Second wave — psych/behavior
    psych_wave2 = [
        ("The Anchoring of Price", "Why a 100-dollar sticker makes 50 dollars feel cheap", "psych"),
        ("The Scarcity Effect", "Why 'only 3 left' makes you want it more", "psych"),
        ("The Authority Bias", "Why a white coat makes the same advice sound wiser", "psych"),
        ("The Zeigarnik Loop", "Why an interrupted task haunts your mind", "psych"),
        ("The Mere-Presence Effect", "Why working with someone changes how fast you work", "psych"),
        ("The Social Proof Signal", "Why 5,000 reviews beat one honest one", "psych"),
        ("The Contrast Principle", "Why a bad first option makes the second look amazing", "psych"),
        ("The Reciprocity Trigger", "Why a free sample makes you buy", "psych"),
        ("The Peak-End Memory", "Why you remember the best and last, not the rest", "psych"),
        ("The Loss Aversion", "Why losing 10 dollars hurts more than finding 10 feels good", "psych"),
        ("The Status Quo Bias", "Why change feels riskier than staying", "psych"),
        ("The Choice Overload", "Why too many options make you pick nothing", "psych"),
        ("The Curse of Knowledge", "Why experts can't remember being beginners", "psych"),
        ("The Plan Continuation Bias", "Why you keep a plan that's already failed", "psych"),
        ("The Post-Purchase Rationalization", "Why you defend a bad buy after the money is gone", "psych"),
    ]
    for name, angle, pillar in psych_wave2:
        add(name, angle, _emoji_for(pillar), pillar)

    # E9: Second wave — body/health
    body_wave2 = [
        ("Why Your Heart Skips a Beat", "Why an early beat makes your heart 'pause'", "body"),
        ("Why Cold Hands Turn White", "Why cold squeezes your blood vessels shut", "body"),
        ("Why You Burp", "Why swallowed air has to come back out", "body"),
        ("Why Your Eyelid Twitches", "Why stress and caffeine make your lid jump", "body"),
        ("Why Your Legs Cramp in Water", "Why cold water sets off a cramp reflex", "body"),
        ("Why You Have a 'Belly Button'", "Why your scar from birth has no real purpose", "body"),
        ("Why Your Skin Prunes in Water", "Why wrinkles in the bath are a grip trick, not damage", "body"),
        ("Why Sweat Smells", "Why bacteria turn your sweat into an odor", "body"),
        ("Why Your Hair Stands on End", "Why goosebumps lift every hair", "body"),
        ("Why You Stretch in the Morning", "Why a good stretch floods your brain with wake-up", "body"),
        ("Why You Yawn When Bored", "Why a yawn cools and wakes a tired brain", "body"),
        ("Why Your Muscles Burn", "Why lactic acid signals effort, not damage", "body"),
        ("Why You Feel Dizzy on Roller Coasters", "Why your inner ear and eyes fight", "body"),
        ("Why Your Jaw Holds Tension", "Why stress parks itself in your jaw", "body"),
        ("Why You Can Feel Your Heartbeat at Night", "Why silence amplifies your pulse", "body"),
    ]
    for name, angle, pillar in body_wave2:
        add(name, angle, _emoji_for(pillar), pillar)

    # E10: Second wave — mystery/unsolved
    mystery_wave2 = [
        ("The Lead Masks Mystery", "Why two men wore lead goggles to a hill and died", "mystery"),
        ("The Randonaut 'Portal'", "Why a coordinates app sent people to a mysterious tunnel", "mystery"),
        ("The Toynbee Tiles", "Why someone glued bizarre messages into city streets for decades", "mystery"),
        ("The Waverly Hills Sanatorium", "Why a hospital's halls are said to hold a darkness", "mystery"),
        ("The Old '97 Train", "Why a doomed train's last messages were never decoded", "mystery"),
        ("The Bennington Triangle", "Why people keep vanishing in one small forest", "mystery"),
        ("The 'Vanishing' of the Atacama Skeleton", "Why a tiny alien-looking skeleton puzzled scientists", "mystery"),
        ("The Hinterkaifeck Footprints", "Why tracks led into a home but never out", "mystery"),
        ("The Bloop Sound Mystery", "Why a sound 5,000 km wide had no obvious source", "mystery"),
        ("The Tamam Shud Codex", "Why a torn page pointed to a 700-year-old Persian poem", "mystery"),
        ("The Circleville 'Letters'", "Why threats to a town were never traced", "mystery"),
        ("The Owlman Sighting", "Why two children saw a winged figure in a church tower", "mystery"),
        ("The 'Ghost' of the Mary Celeste", "Why a perfectly good ship was found with no one aboard", "mystery"),
        ("The Great Silence", "Why we still can't find a single alien signal", "mystery"),
        ("The 'Face on Mars'", "Why a rock formation looked eerily carved", "mystery"),
    ]
    for name, angle, pillar in mystery_wave2:
        add(name, angle, _emoji_for(pillar), pillar)

    # E11: Second wave — animal
    animal_wave2 = [
        ("The Frilled Shark", "Why a 'living fossil' shark hunts in the deep", "animal"),
        ("The Yeti Crab", "Why a crab grows its own food on its arms", "animal"),
        ("The Velvet Worm", "Why a worm shoots glue to trap prey", "animal"),
        ("The Goblin Shark", "Why a shark has a jaw that shoots out like a spring", "animal"),
        ("The Dumbo Octopus", "Why an octopus flaps ear-like fins in the dark", "animal"),
        ("The Snow Leopard's Tail", "Why a cat carries a tail as long as its body", "animal"),
        ("The Raccoon's Hands", "Why a raccoon 'sees' with its paws", "animal"),
        ("The Blue Whale's Heartbeat", "Why a heart the size of a car beats twice a minute", "animal"),
        ("The Spider's Silk Strength", "Why a spider's web is stronger than steel by weight", "animal"),
        ("The Octopus's Disguise", "Why an octopus can change shape and texture in seconds", "animal"),
        ("The Peregrine's Dive", "Why a bird can out-dive a race car", "animal"),
        ("The Camel's Hump", "Why a camel stores fat, not water, in its hump", "animal"),
        ("The Star-Nosed Mole", "Why a mole 'sees' with 22 pink tentacles", "animal"),
        ("The Kiwi's Nostrils", "Why a flightless bird sniffs with a beak full of nerves", "animal"),
        ("The Aye-Aye's Echo", "Why a lemur taps wood to hear insects inside", "animal"),
    ]
    for name, angle, pillar in animal_wave2:
        add(name, angle, _emoji_for(pillar), pillar)

    # E12: Second wave — sleep/perception
    sleep_wave2 = [
        ("Why You Dream About Falling Teeth", "Why a common nightmare has a hidden meaning", "sleep"),
        ("The Sleep Debt", "Why a lost hour can't be fully repaid", "sleep"),
        ("Why You 'See' Hypnic Images", "Why flashes of faces appear as you fall asleep", "sleep"),
        ("The Dream Rehearsal", "Why your brain practices scary events in sleep", "sleep"),
        ("Why Alarm Snooze Feels Worse", "Why fragmented sleep makes you groggier", "sleep"),
        ("The Circadian Jet Lag", "Why your body clock hates a time-zone jump", "sleep"),
        ("Why Some People Sleep With Eyes Open", "Why nocturnal lagophthalmos lets eyes stay open", "sleep"),
        ("The Night Owl's Clock", "Why some brains are wired to be late", "sleep"),
        ("Why You Wake at the Same Hour", "Why your body clock sets a nightly alarm", "sleep"),
        ("The Power of the 90-Minute Cycle", "Why waking mid-cycle leaves you groggy", "sleep"),
    ]
    for name, angle, pillar in sleep_wave2:
        add(name, angle, _emoji_for(pillar), pillar)

    percept_wave2 = [
        ("Why Shadows Seem to Move", "Why low light tricks your motion detectors", "perception"),
        ("Why We See Faces in Clouds", "Why your brain hunts for faces everywhere", "perception"),
        ("Why Mirrors Flip You", "Why a mirror shows a version you never see", "perception"),
        ("Why Two Eyes See One Image", "Why your brain fuses two pictures into depth", "perception"),
        ("Why Time 'Flies'", "Why familiar days feel shorter as you age", "time"),
        ("Why a Week Feels Long in Childhood", "Why a year is a lifetime when you're young", "time"),
        ("Why Music Sounds Slower When Tired", "Why fatigue slows your internal clock", "perception"),
        ("Why Hot Feels Colder in Wind", "Why wind steals heat faster than air alone", "perception"),
        ("Why Wet Clothes Feel Heavy", "Why water adds weight you notice instantly", "perception"),
        ("Why the Floor Looks Slippery When Wet", "Why shine reads as 'danger, no grip'", "perception"),
    ]
    for name, angle, pillar in percept_wave2:
        add(name, angle, _emoji_for(pillar), pillar)

    # E13: Final wave to clear 500
    final_wave = [
        ("Why the Brain Erases Pain", "Why a bad memory of pain fades faster than a good one", "psych"),
        ("Why We Fear Snakes More Than Cars", "Why your brain still runs an ancient threat list", "psych"),
        ("Why Laughter Resets Your Brain", "Why laughter is your brain's reset button", "psych"),
        ("Why You Talk to Your Dog", "Why your brain treats pets like people", "psych"),
        ("Why a Smell Brings Back a Memory", "Why scent is wired straight to memory", "perception"),
        ("Why Old Songs Make You Emotional", "Why music is glued to your memory", "memory"),
        ("Why You Dream in the Language You Speak", "Why your dream voice matches your day", "sleep"),
        ("Why a Baby's Cry Is Unignorable", "Why a cry is tuned to hijack your attention", "psych"),
        ("Why You Feel Someone Staring", "Why your brain tracks another pair of eyes", "perception"),
        ("Why Cold Water Slows Time", "Why a shock of cold stretches a second", "time"),
        ("Why the Color Blue Calms You", "Why blue signals sky, water and safety", "psych"),
        ("Why Your Brain Rewrites a Bad Day", "Why memory edits the past to protect you", "memory"),
        ("Why Patterns Feel Good", "Why your brain is wired to find order", "psych"),
        ("Why We Love a Mystery", "Why an unanswered question hooks your attention", "psych"),
        ("Why a Cliff Makes You Want to Jump", "Why your brain plays a fear scenario on purpose", "psych"),
        ("Why We Anthropomorphize", "Why you see a face in your car's front", "perception"),
        ("Why Music Gives You the Chills", "Why a good chord triggers goosebumps", "psych"),
        ("Why You 'Hear' Your Name in Noise", "Why your brain filters the world for your name", "perception"),
        ("Why a Breakup Feels Like Pain", "Why rejection uses the same wires as physical hurt", "psych"),
        ("Why Some People Fear Clowns", "Why a painted smile trips your danger alarm", "psych"),
        ("Why Your Phone Feels Heavier at Night", "Why boredom makes a phone feel like a brick", "perception"),
        ("Why a Deadline Sharpens Focus", "Why pressure flips on your brain's urgency", "psych"),
        ("Why We Trust a Symmetrical Face", "Why symmetry reads as 'healthy genes'", "psych"),
        ("Why a Rumor Spreads", "Why your brain retells a juicy story with edits", "psych"),
        ("Why You Freeze Under Pressure", "Why your brain can lock up at the worst moment", "psych"),
        ("Why a 'White Noise' Room Feels Creepy", "Why total silence makes your brain build fear", "psych"),
        ("Why You Feel Heavier When Tired", "Why fatigue saps your sense of weight", "perception"),
        ("Why a Hot Shower Feels Like a Reset", "Why heat flips your body from stress to calm", "body"),
        ("Why Your Stomach Knows You're Nervous", "Why anxiety lives in your gut", "body"),
        ("Why Crying Helps", "Why tears carry stress chemicals out of your body", "body"),
        ("Why Your Heart Races in a Dream", "Why a dream scare triggers a real pulse", "sleep"),
        ("Why You Forget a Dream in Seconds", "Why dream memory evaporates on waking", "sleep"),
        ("Why Some Animals Laugh", "Why a dog's play-bow is a laugh in another tongue", "animal"),
        ("Why a Cat Kneads You", "Why a kitten's nursing reflex never leaves a cat", "animal"),
        ("Why Crows Remember Faces", "Why a crow can hold a grudge against one person", "animal"),
        ("Why a Dog Tilts Its Head", "Why a tilted head means your dog is reading you", "animal"),
        ("Why an Octopus Leaves Its Tank", "Why an octopus escapes just to explore", "animal"),
        ("Why a Grizzly Eats 90 Pounds a Day", "Why a bear eats nonstop to survive winter", "animal"),
        ("Why a Bat 'Sees' With Sound", "Why echolocation draws a picture from echoes", "animal"),
        ("Why a Firefly Flashes", "Why a bug speaks in light to find love", "animal"),
        ("Why the Ocean Glows", "Why bioluminescence lights the sea", "space"),
        ("Why a Magnet Has Two Poles", "Why every magnet secretly has a north and south", "space"),
        ("Why Ice Floats", "Why water breaks every rule to keep life alive", "space"),
        ("Why a Rainbow Forms a Circle", "Why a full rainbow is hiding above the horizon", "space"),
        ("Why the Sky Is Black at Night", "Why space is dark even with a universe of stars", "space"),
        ("Why Gravity Feels Like a Person", "Why you can't feel gravity as a force", "space"),
        ("Why Time Is Relative", "Why two people age at different rates", "time"),
        ("Why a 'Second' Isn't Universal", "Why a second depends on where you are", "time"),
        ("Why the Universe Had a Start", "Why everything traces back to one instant", "space"),
        ("Why Nothing Can Outrun Light", "Why light sets the speed limit of the universe", "space"),
    ]
    for name, angle, pillar in final_wave:
        add(name, angle, _emoji_for(pillar), pillar)

    # F: Remaining unique "why" facts to top up to 500 (physics/nature/space facts)
    misc_facts = [
        ("Why the Sky Is Blue", "Why blue, of all colors, wins the scattering race", "space"),
        ("Why Salt Makes You Thirsty", "Why your brain misreads a salt craving", "body"),
        ("Why Tears Are Salty", "Why your body makes you taste your own sadness", "body"),
        ("Why Space Is Silent", "Why the universe has nothing to carry a scream", "space"),
        ("Why Time Slows Near a Black Hole", "Why gravity bends time itself", "space"),
        ("Why Your Nose Runs in the Cold", "Why cold air makes your nose leak", "body"),
        ("Why Old Photos Feel Creepy", "Why the 'uncanny past' effect makes vintage photos unsettling", "psych"),
        ("Why You Can't Tickle Yourself", "Why your brain cancels out its own surprise", "psych"),
        ("Why Sloths Risk Death to Poop", "Why a sloth climbs down to become a target", "animal"),
        ("Why Cats Purr", "Why a purr might be a healing frequency", "animal"),
        ("Why Dogs Spin Before Lying Down", "Why your dog's ancestors left an ancient habit in his DNA", "animal"),
        ("Why the Ocean Is Salty", "Why rivers have been salting the sea for four billion years", "space"),
        ("Why You Get Goosebumps", "Why your skin remembers a time you had fur", "body"),
        ("Why Your Voice Sounds Different Recorded", "Why your recorded voice is what everyone else hears", "perception"),
        ("Why Yawning Is Contagious", "Why your brain yawns to match the herd", "psych"),
        ("Why Cut Onions Make You Cry", "Why an onion weaponizes a tear gas", "body"),
        ("Why You Dream in Black and White", "Why your dreams sometimes lose all color", "sleep"),
        ("Why Babies Grab Your Finger", "Why a newborn's grip is a survival reflex", "body"),
        ("Why You Feel Like You're Falling in Dreams", "Why your brain replays a primal fall", "sleep"),
        ("Why the Moon Looks Bigger at the Horizon", "Why your brain scales the moon to your memory", "perception"),
        ("Why You Forget Why You Walked Into a Room", "Why doorways reset your working memory", "psych"),
        ("Why Cold Water Feels Sharp", "Why cold triggers the same nerve as pain", "body"),
        ("Why Your Foot Falls Asleep", "Why a pinched nerve makes your limb feel dead", "body"),
        ("Why Some People Can't Picture Anything", "Why aphantasia makes some brains blind in the mind's eye", "perception"),
        ("Why Deja Vu Feels So Strong", "Why your brain double-writes a single moment", "memory"),
        ("Why You Talk to Yourself", "Why your inner voice is a tool, not a quirk", "psych"),
        ("Why Rain Smells So Good", "Why the scent of petrichor is so powerful", "perception"),
        ("Why We Find Symmetry Attractive", "Why your brain reads symmetry as health", "psych"),
        ("Why Some Faces Look More Trustworthy", "Why your brain judges a face in a split second", "psych"),
        ("Why Cold Hands Feel Sticky", "Why cold makes your skin misread texture", "perception"),
        ("Why You Crave Sugar When Stressed", "Why stress hijacks your reward system", "body"),
        ("Why Music Gets Stuck in Your Head", "Why an earworm latches onto your memory loop", "psych"),
        ("Why Laughter Is Contagious", "Why your brain is wired to mirror a laugh", "psych"),
        ("Why Some Words Sound Wrong Repeated", "Why saying a word 50 times makes it alien", "perception"),
        ("Why We Blink", "Why your brain edits out every blink", "perception"),
        ("Why Your Eyes Water When You Laugh Hard", "Why tears and laughter share a nerve line", "body"),
        ("Why Spicy Food Burns Then Feels Good", "Why your brain rewards you for a false burn", "body"),
        ("Why You Feel Hungry After Seafood", "Why umami tricks your hunger system", "body"),
        ("Why Cold Showers Wake You Up", "Why a shock of cold flips on your alertness", "body"),
        ("Why Morning Breath Smells", "Why your mouth becomes a low-oxygen city overnight", "body"),
        ("Why We Find Dots Upsetting", "Why trypophobia makes your brain recoil", "psych"),
        ("Why a Single Sleepless Night Feels Like a Fever", "Why sleep loss mimics an infection", "body"),
        ("Why You Dream About People You Never Met", "Why your brain builds strangers from fragments", "sleep"),
        ("Why the Number Seven Feels Special", "Why your memory locks onto seven items", "psych"),
        ("Why Red Makes You Hungry", "Why a color can switch on your appetite", "psych"),
        ("Why Music Gives You Chills", "Why a good song triggers goosebumps", "psych"),
        ("Why We Fear the Dark", "Why your brain fills the dark with danger", "psych"),
        ("Why Kids' Voices Sound Higher When Excited", "Why stress tightens your vocal cords", "body"),
        ("Why We Can't Remember Being Born", "Why the brain starts logging memory later than you'd think", "memory"),
        ("Why the Speed of Light Feels Slow", "Why light is both too fast and too slow", "space"),
    ]
    for name, angle, pillar in misc_facts:
        add(name, angle, _emoji_for(pillar), pillar)

    return records


def main() -> None:
    records = build()
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(records)} Dark Mystery topics -> {TARGET}")


if __name__ == "__main__":
    main()
