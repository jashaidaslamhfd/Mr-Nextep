"""
Niche Strategy Module for Nextep Pipeline
OPTIMIZED FOR: HIGH RETENTION + PSYCHOLOGICAL PACING

2026 UPDATE:
- Topic pool expanded from 150 → 360+ static topics
- Dynamic LLM topic generation when pool runs low
- Clickbait hooks removed (YouTube penalizes "Doctors don't want" patterns)
- Engagement-bait CTAs removed (YouTube penalizes "like if", "comment 🤯")
- All hooks/CTAs are honest, curiosity-driven, natural-sounding
"""

import logging
import random
import os
import re
from typing import List, Dict, Optional

try:
    from script_generator import repair_mojibake
except ImportError:  # keeps this module importable standalone/in tests
    def repair_mojibake(text: str) -> str:
        return text

logger = logging.getLogger(__name__)

# ============================================
# 1. EXPANDED DARK TOPICS (360+ static topics)
# ============================================
DARK_TOPICS = [
    # ── High Demand / Low Competition Micro-Niches ──
    "What Happens When You Sleep Wrong on Your Neck",
    "What Happens When You Sleep With Your Mouth Open",
    "Why Your Body Fights Weight Loss While You Sleep",
    "Why Your Brain Is Active Immediately After You Wake Up",
    "Why Your Body Randomly Needs to Fart",
    "What Happens When You Sleep On Your Stomach",
    "What Happens When You Sleep With a Fan on All Night",
    "Why Your Brain Doesn't Understand Fast Talking When You're Tired",
    "Why Your Body Feels Older Than It Should",
    "What Happens When You Sleep Immediately After Eating",
    "Why Your Brain Traps You in Past Memories",
    "What Happens When You Sleep With Wet Hair",
    "What Happens When You Sleep Late Every Night",
    "Why Your Body Randomly Twitches Right As You Fall Asleep",
    "Why You Can Hear Your Own Heartbeat When You Lie Down",
    
    # ── Brain / Mind / Neuroscience (50+) ──
    "Your Heart Has Its Own Brain",
    "This Happens Inside Your Brain When You Sleep",
    "Why You Get Goosebumps",
    "Your Brain Eats Itself While You Sleep",
    "The Part of Your Brain That Never Sleeps",
    "Why Your Brain Lies to You Every Day",
    "This Is What Deja Vu Actually Is",
    "Your Brain Can Rewire Itself Overnight",
    "The Reason You Talk to Yourself in Your Head",
    "Why Nightmares Exist At All",
    "Your Brain Deletes Memories on Purpose",
    "The Real Reason You Freeze Under Pressure",
    "Why Some People Never Forget a Face",
    "Your Brain Has a Hidden Backup System",
    "The Chemical That Makes You Fall in Love",
    "Why Your Brain Processes Fear Faster Than Logic",
    "The Part of Your Brain That Never Stops Growing",
    "Why You Can't Remember Being a Baby",
    "Your Brain Has Its Own Immune System",
    "The Reason You Get Brain Freeze",
    "Why Your Brain Shrinks When You're Depressed",
    "The Secret Language of Your Brain Waves",
    "Why Your Brain Makes You See Ghosts",
    "The Reason Your Brain Forgets Names",
    "Your Brain Creates Reality, Not Just Perceives It",
    "How Your Brain Decides What to Ignore",
    "Why Your Brain Hears Music That Isn't There",
    "The Part of Your Brain That Controls Your Accent",
    "Why Your Brain Can't Multitask",
    "What Happens to Your Brain During Meditation",
    "Why Your Brain Prefers Bad News Over Good",
    "The Reason You Get Songs Stuck in Your Head",
    "How Your Brain Predicts the Future Every Second",
    "Why Your Brain Treats Rejection Like Physical Pain",
    "The Chemical That Makes You Procrastinate",
    "Why Your Brain Is More Active at Night",
    "How Your Brain Rewires After a Breakup",
    "The Reason You Zone Out During Conversations",
    "Why Your Brain Creates False Memories",
    "What Your Brain Does in the First 30 Seconds of Waking",
    "Why Your Brain Can't Resist Gossip",
    "The Part of Your Brain That Recognizes Faces",
    "How Your Brain Learns While You Sleep",
    "Why Your Brain Gets Addicted to Social Media",
    "The Reason You Feel Time Speed Up as You Age",
    "Why Your Brain Hates Uncertainty",
    "How Your Brain Processes Pain Differently at Night",
    "The Reason You Get Dizzy When You Spin",
    "Why Your Brain Craves Patterns in Randomness",
    "What Happens to Your Brain When You're Bored",

    # ── Heart / Blood / Circulatory (40+) ──
    "Your Body Has 60,000 Miles of Veins",
    "Why Your Heart Skips a Beat",
    "Your Blood Has a Secret Weapon",
    "Your Heart Beats 100,000 Times a Day Without Asking",
    "The Sound Your Heart Makes That You've Never Heard",
    "Why Your Face Turns Red When You're Angry",
    "The Reason Cold Hands Mean a Warm Heart",
    "Your Blood Changes Color Inside Your Body",
    "The Secret Behind Your Heartbeat",
    "The Reason Your Veins Look Blue Under Your Skin",
    "Your Heart Has Its Own Electrical System",
    "The Reason Your Pulse Changes When You Lie",
    "Your Blood Vessels Could Circle the Earth",
    "Why Your Heart Breaks When You're Sad",
    "The Hidden Power of Your Blood Type",
    "Why Your Heart Beats Faster in the Morning",
    "The Reason Your Blood Clots When You Cut Yourself",
    "Your Heart Has a Memory of Its Own",
    "Why Your Blood Pressure Rises When You're Stressed",
    "How Your Blood Fights Infections Without You Knowing",
    "The Reason Your Veins Look Blue Under Your Skin",
    "Why Your Heart Rate Changes When You Breathe",
    "What Happens to Your Blood When You're Scared",
    "The Reason Your Blood Takes Time to Stop Bleeding",
    "Why Your Heart Pounds After Drinking Coffee",
    "How Your Blood Carries Oxygen to Every Cell",
    "The Reason Your Blood Is Thicker in the Morning",
    "Why Your Heart Slows Down When You Dive Into Water",
    "What Happens to Your Blood During Exercise",
    "The Reason Your Pulse Is Felt in Your Neck",
    "Why Your Blood Cells Live for Only 120 Days",
    "How Your Heart Knows to Beat Faster When You Stand Up",
    "The Reason Your Blood Looks Different in Veins vs Arteries",
    "Why Your Heart Has Four Chambers Instead of Two",
    "What Happens to Your Blood When You're Dehydrated",
    "The Reason Your Blood Pressure Drops When You're Relaxed",
    "Why Your Heart Beats Differently When You're Sick",
    "How Your Blood Vessels Expand in Heat and Shrink in Cold",
    "The Reason Your Blood Has a Metallic Taste",

    # ── Lungs / Breathing (30+) ──
    "Your Lungs Can Drown You From Inside",
    "Why You Yawn When You See Someone Else Yawn",
    "The Real Reason You Can't Tickle Yourself",
    "Why Holding Your Breath Feels Like Panic",
    "Your Lungs Have Their Own Cleaning System",
    "The Reason You Sneeze When You Look at Light",
    "Your Breathing Changes When You Think",
    "Why Your Lungs Never Fully Empty",
    "The Secret Power of Deep Breathing",
    "Why You Breathe Differently at Night",
    "The Reason Your Lungs Hurt in Cold Weather",
    "Your Lungs Can Heal Themselves",
    "Why Asthma Attacks Happen at Night",
    "The Hidden Connection Between Breath and Anxiety",
    "Why Your Breathing Slows When You Sleep",
    "How Your Lungs Filter 11,000 Liters of Air Daily",
    "The Reason You Cough When Something Goes Down the Wrong Pipe",
    "Why Your Breathing Changes When You're Focused",
    "What Happens to Your Lungs at High Altitude",
    "The Reason Your Lungs Make Sound When You Breathe",
    "How Your Lungs Self-Clean Every Time You Cough",
    "The Reason Your Breathing Speeds Up When You're Excited",
    "Why Your Lungs Feel Heavy After a Long Nap",
    "What Happens Inside Your Lungs When You Laugh",
    "The Reason Your Breathing Stops Briefly When You Sneeze",
    "Why Your Lungs Expand More on One Side Than the Other",
    "How Your Body Controls Breathing Without You Thinking",
    "The Reason You Breathe Through One Nostril at a Time",
    "Why Your Lungs Are the Only Organs That Float on Water",

    # ── Bones / Muscles (30+) ──
    "The Bone That Breaks Most in Fights",
    "Your Bones Are Being Replaced Right Now",
    "Why Cracking Your Knuckles Makes That Sound",
    "The Strongest Muscle in Your Body Isn't What You Think",
    "Why You Lose Height During the Day",
    "Your Bones Are Stronger Than Steel",
    "The Muscle That Never Tires",
    "Why Your Jaw Is the Strongest Muscle",
    "Your Skeleton Regenerates Every 10 Years",
    "The Bone That's Actually Fused at Birth",
    "Why Your Muscles Get Sore After Exercise",
    "Why Your Bones Weaken With Age",
    "The Strongest Bone in Your Body",
    "Why You Can't Move When You Sleep",
    "How Your Muscles Grow While You Rest",
    "The Reason Your Bones Ache When the Weather Changes",
    "Why Your Tongue Is the Most Flexible Muscle",
    "What Happens to Your Bones in Zero Gravity",
    "The Reason Your Muscles Twitch When You're Tired",
    "Why Your Skull Isn't One Solid Bone",
    "How Your Body Decides Which Muscles to Use First",
    "The Reason Your Knees Crack When You Squat",
    "Why Your Bones Store Calcium",
    "What Happens to Your Muscles When You Stretch",
    "The Reason Your Grip Strength Changes Throughout the Day",
    "Why Your Body Has More Muscles Moving Your Fingers Than Your Arm",
    "How Your Bones Communicate With Your Brain",
    "The Reason Your Muscles Feel Stiff After Sitting",
    "Why Your Jaw Muscle Can Exert 200 Pounds of Force",

    # ── Digestive / Organs (40+) ──
    "Your Stomach Can Digest Itself",
    "The Organ You Can Live Without",
    "Your Gut Has Its Own Nervous System",
    "Why Your Stomach Growls Even When You're Not Hungry",
    "The Organ That Regrows Itself Completely",
    "Why You Can't Breathe and Swallow at the Same Time",
    "Your Liver Can Regrow in 30 Days",
    "The Reason You Get Heartburn",
    "Your Gut Has More Neurons Than Your Spinal Cord",
    "The Organ That Decides Your Mood",
    "Why Your Digestion Slows at Night",
    "Why Your Stomach Hurts When You're Nervous",
    "The Organ That Controls Your Appetite",
    "Why You Get Food Cravings",
    "How Your Stomach Acid Can Dissolve Metal",
    "The Reason You Feel Bloated After Eating Certain Foods",
    "Why Your Gut Bacteria Influence Your Emotions",
    "What Happens to Your Food After You Swallow",
    "Why Your Intestines Are 25 Feet Long",
    "How Your Liver Filters 1.4 Liters of Blood Per Minute",
    "The Reason You Get Butterflies in Your Stomach",
    "Why Your Body Rejects Food When You're Stressed",
    "What Happens to Your Kidneys When You Drink Too Much Water",
    "The Reason Your Appendix Exists Even Though It Seems Useless",
    "Why Your Gut Produces 95% of Your Body's Serotonin",
    "How Your Pancreas Decides When to Release Insulin",
    "The Reason You Feel Tired After a Big Meal",
    "Why Your Stomach Lining Replaces Itself Every Few Days",
    "What Happens to Your Organs When You Hold Your Pee",
    "The Reason Your Liver Is Your Largest Internal Organ",
    "Why Your Gallbladder Stores Bile for Digestion",
    "How Your Small Intestine Absorbs Nutrients",
    "The Reason You Get Hungry at the Same Time Every Day",
    "Why Your Colon Reabsorbs Water From Waste",
    "What Happens to Your Spleen When You Exercise",
    "The Reason Your Thymus Shrinks as You Age",
    "Why Your Adrenaline Glands Sit on Top of Your Kidneys",
    "How Your Body Signals Hunger vs Thirst",
    "The Reason Your Digestive System Slows Down When You're Sick",

    # ── Skin / Senses (40+) ──
    "Your Skin Replaces Itself Every Month",
    "Why Your Eyes Never Actually Stop Moving",
    "The Reason Your Ears Never Stop Growing",
    "Why You Can't See Your Own Blind Spot",
    "Your Fingerprints Started Forming Before You Were Born",
    "Your Skin Has Its Own Immune System",
    "Why Your Hair Changes Color With Age",
    "The Reason You Get Goosebumps When Cold",
    "Your Eyes Have a Blind Spot You Never Notice",
    "Why Your Sense of Smell Changes at Night",
    "The Secret of Your Skin's Microbiome",
    "Why Your Skin Changes With Stress",
    "The Reason You Get Dark Circles Under Your Eyes",
    "Why Your Fingers Prune in Water",
    "The Hidden Power of Your Sense of Touch",
    "How Your Eyes Adjust to Darkness in 30 Minutes",
    "The Reason Your Skin Gets Oily in Certain Spots",
    "Why Your Nose Runs When You Eat Spicy Food",
    "What Happens to Your Skin When You're Cold",
    "The Reason Your Eyes Water When You Yawn",
    "Why Your Skin Itches When You're Healing",
    "How Your Ears Maintain Your Balance",
    "The Reason Your Pupils Dilate When You're Attracted",
    "Why Your Skin Tans Instead of Burns Sometimes",
    "What Happens to Your Hair When You're Stressed",
    "The Reason Your Eyes Blink 15,000 Times a Day",
    "Why Your Tongue Has Different Zones for Different Tastes",
    "How Your Skin Detects Temperature Changes",
    "The Reason Your Ears Pop on Airplanes",
    "Why Your Nose Can Detect Over 1 Trillion Scents",
    "What Happens to Your Skin When You Don't Sleep",
    "The Reason Your Eyelashes Fall Out Every Few Months",
    "Why Your Fingernails Grow Faster Than Your Toenails",
    "How Your Eyes Produce Tears for Different Emotions",
    "The Reason Your Skin Wrinkles in Water",
    "Why Your Body Hair Stands Up When You're Scared",
    "What Happens to Your Taste Buds as You Age",
    "The Reason Your Eyes See Floaters Sometimes",
    "Why Your Skin Gets Dry in Winter",
    "How Your Inner Ear Detects Sound Vibrations",

    # ── Immune / Hormones / Cells (40+) ──
    "Your Immune System Has a Memory",
    "Why Your Body Runs a Fever on Purpose",
    "The Reason Your Wounds Itch When Healing",
    "How Your White Blood Cells Hunt Bacteria",
    "Why You Feel Worse Before You Feel Better When Sick",
    "The Hormone That Makes You Feel Awake at Night",
    "Why Your Body Produces Mucus When You're Sick",
    "The Reason Your Lymph Nodes Swell When You're Ill",
    "How Your Body Creates Antibodies in 7 Days",
    "Why Your Immune System Attacks Your Own Body Sometimes",
    "Why Your Body Temperature Drops at 3 AM",
    "How Your Skin Acts as Your First Line of Defense",
    "The Reason Your Body Shivers to Fight Infection",
    "Why Your Wound Heals Faster During the Day",
    "The Hormone That Controls Your Sleep Cycle",
    "Why Your Body Makes Histamine When You Have Allergies",
    "The Reason Your Saliva Contains Healing Properties",
    "How Your Body Detects and Kills Cancer Cells Daily",
    "Why Your Immune System Weakens When You Don't Sleep",
    "The Reason Your Body Swells Around an Injury",
    "Why Your Tears Contain a Natural Antibiotic",
    "How Your Bone Marrow Produces 200 Billion Blood Cells Daily",
    "The Reason Your Body Aches When You Have the Flu",
    "Why Your Immune System Is Stronger in the Morning",
    "The Hormone That Makes You Feel Hungry",
    "Why Your Body Produces Cortisol Under Stress",
    "The Reason Your Body Burns More Calories When Sick",
    "How Your Body Fights Off a Virus You've Never Had Before",
    "Why Your Lymphatic System Has No Pump Like Your Heart",
    "The Reason Your Body Temperature Fluctuates Throughout the Day",
    "Why Your Immune Cells Can Swim Through Your Tissues",
    "How Your Body Remembers Every Virus It Has Ever Fought",
    "The Reason Your Nose Gets Stuffy at Night When Sick",
    "Why Your Body Increases White Blood Cell Count During Exercise",
    "The Hormone That Makes You Feel Full After Eating",
    "Why Your Body Produces Melatonin When It Gets Dark",
    "The Reason Your Muscles Ache the Day After a Workout",
    "How Your Body Heals a Broken Bone Without You Thinking",
    "Why Your Immune System Treats a Splinter Like an Invasion",

    # ── Sleep / Dreams (30+) ──
    "Why Your Brain Paralyzes You While You Sleep",
    "The Reason You Dream in 90-Minute Cycles",
    "How Your Brain Cleans Itself Every Night",
    "Why You Sometimes Jerk Awake When Falling Asleep",
    "The Reason You Can't Breathe Normally During REM Sleep",
    "How Your Body Grows While You Sleep",
    "Why Your Brain Replays Your Day During Sleep",
    "The Reason You Wake Up Before Your Alarm Sometimes",
    "Why Your Body Temperature Drops When You Fall Asleep",
    "How Your Eyes Move During REM Sleep",
    "The Reason You Talk in Your Sleep Sometimes",
    "Why Your Brain Blocks Sound While You Sleep",
    "The Reason You Forget Most of Your Dreams",
    "Why Sleep Deprivation Makes You Hallucinate",
    "How Your Brain Decides What to Dream About",
    "The Reason You Feel Groggy After a Long Nap",
    "Why Your Body Heals Faster During Deep Sleep",
    "The Reason Your Brain Releases Growth Hormone at Night",
    "Why You Sometimes Act Out Your Dreams",
    "How Your Brain Filters Noise While You Sleep",
    "The Reason You Need More Sleep When You're Sick",
    "Why Your Brain Is More Creative After Sleep",
    "The Reason Your Muscles Are Completely Relaxed During REM",
    "Why You Can Sometimes Control Your Dreams",
    "How Your Circadian Rhythm Works Without Sunlight",
    "The Reason You Feel Hungrier After a Bad Night's Sleep",
    "Why Your Brain Prunes Unnecessary Memories During Sleep",
    "The Reason Your Body Twitches in the First Stage of Sleep",
    "Why You Sleep Better in a Cold Room",
    "How Your Brain Recharges Your Immune System While You Sleep",

    # ── Evolution / Odd Body Facts (30+) ──
    "Why Humans Have a Tailbone But No Tail",
    "The Reason You Have an Appendix That Seems Useless",
    "Why Your Body Hair Is Mostly Gone Compared to Other Animals",
    "The Reason Goosebumps Still Exist in Humans",
    "Why Humans Can't Make Vitamin C Like Most Animals",
    "The Reason You Have Wisdom Teeth That Need Removal",
    "Why Your Body Stores Fat for Winter Like a Hibernating Animal",
    "The Reason Your Ear Muscles Are Vestigial",
    "Why Humans Lost the Ability to Smell Like Other Mammals",
    "The Reason You Have a Palmar Grasp Reflex as a Baby",
    "Why Your Body Still Reacts to Shadows Like a Threat",
    "The Reason Your Appendix May Not Be Useless After All",
    "Why Humans Have More Sweat Glands Than Any Other Animal",
    "The Reason Your Body Can't Digest Grass Like Cows",
    "Why Your Eyes Can See More Shades of Green Than Any Other Color",
    "The Reason Your Body Has a Fight-or-Flight Response",
    "Why Humans Are One of the Few Animals That Can Swim Naturally",
    "The Reason Your Body Gets Goosebumps From Music",
    "Why You Have the Same Number of Neck Bones as a Giraffe",
    "The Reason Your Body Can Survive Without a Spleen",
    "Why Humans Are the Only Animals That Cry Emotional Tears",
    "The Reason Your Body Still Has a Startle Reflex",
    "Why Your Body Burns Calories Just to Stay Alive",
    "The Reason You Can Survive With Only One Kidney",
    "Why Humans Have Dominant Hands Unlike Most Animals",
    "The Reason Your Body Produces Adrenaline in Danger",
    "Why Your Body Can Heal a Cut Without You Thinking",
    "The Reason You Have More Bacteria in Your Body Than Human Cells",
    "Why Your Body Can Adapt to High Altitude Over Time",
    "The Reason Your Body Temperature Is 98.6 Degrees Fahrenheit",

    # ── Senses / Perception (30+) ──
    "Why You Can't Lick Your Own Elbow",
    "The Reason Your Voice Sounds Different on a Recording",
    "Why You Can't Tickle Yourself",
    "The Reason Cold Water Feels Colder Than Cold Air",
    "Why Your Brain Fills In Your Blind Spot Automatically",
    "The Reason Spicy Food Isn't Actually a Taste",
    "Why You See Colors That Don't Exist",
    "The Reason You Can't Smell Your Own Perfume After a While",
    "Why Your Brain Makes You Think the Moon Follows You",
    "The Reason Hot Water Can Feel Cold Sometimes",
    "Why Your Eyes See Afterimages After Looking at Bright Lights",
    "The Reason You Can Feel Your Pulse in Your Fingertips",
    "Why Your Brain Hears Phantom Phone Vibrations",
    "The Reason Food Tastes Different When You're Sick",
    "Why You Can't Read in Your Dreams",
    "The Reason Your Brain Perceives Motion in Static Images",
    "Why Music Gives You Goosebumps Sometimes",
    "The Reason You Feel Phantom Limbs After Amputation",
    "Why Your Brain Treats Social Rejection Like Physical Pain",
    "The Reason You Can Feel the Weight of Someone Staring",
    "Why Your Brain Creates the Illusion of Smooth Video From Still Frames",
    "The Reason Red and Blue Text on Screen Causes Eye Strain",
    "Why Your Brain Hears Different Words From the Same Sound",
    "The Reason You Can Feel Temperature Through Your Fingertips",
    "Why Your Brain Prefers Faces That Look Like Your Own",
    "The Reason You Can Detect Someone's Gaze From Across a Room",
    "Why Your Brain Processes Smells Faster Than Any Other Sense",
    "The Reason You Get Motion Sick in a Car But Not While Walking",
    "Why Your Brain Fills In Silences in Conversation",
    "The Reason You Can Balance on One Foot With Your Eyes Closed",
    
    # ── 🩺 Pain & Signals (UNTAPPED — 0 videos, competitor avg 410K views) ──
    "Why Your Head Hurts When You Eat Ice Cream Too Fast",
    "The Hidden Cause of Your Random Sharp Chest Pain",
    "Why Your Back Hurts After Sitting All Day",
    "Your Body Warning Signals You Have Been Ignoring",
    "Why Old Injuries Hurt When the Weather Changes",
    "The Real Reason Your Joints Crack and Pop",
    "Why Your Stomach Hurts When You Are Anxious",
    "Why Your Muscles Feel Sore 2 Days After Exercise",
    "Why Your Neck Hurts After Sleeping Wrong",
    "The Hidden Reason Behind Your Random Headaches",
    "Why Your Feet Ache After Standing All Day",
    "What That Sharp Pain in Your Side Actually Means",
    "Why Your Wrist Hurts When You Type Too Much",
    "The Warning Pain in Your Lower Back You Ignore",
    "Why Your Jaw Hurts When You Wake Up",
    "What Happens When Your Nerve Gets Pinched",
    "Why Your Shoulder Pops When You Lift Your Arm",
    "The Real Reason Your Legs Cramp at Night",
    "Why Your Heel Hurts When You First Stand Up",
    "What That Tingling in Your Hands Really Means",
    "Why Your Hip Pops When You Walk Upstairs",
    "The Pain Signal Your Body Sends Before a Headache",
    "Why Your Eye Hurts When You Look at Screens Too Long",
    "What Happens When You Ignore Back Pain Too Long",
    "Why Your Knees Ache When It Rains",
    "The Reason Your Muscles Spasm After a Workout",
    "Why Your Skin Hurts When You Have the Flu",
    "What That Sharp Stabbing Pain in Your Foot Means",
    "Why Your Body Sends Random Pains That Vanish",
    "The Hidden Link Between Stress and Body Pain",

    # ── 👁️ Sensory Phenomena (LOW competition — 6 videos, competitor avg 520K) ──
    "Why Your Ears Ring in Absolute Silence",
    "Why Your Foot Falls Asleep and Feels Like Static",
    "Why You See Glowing Spots After Looking at Bright Light",
    "Your Hands Wrinkling in Water Is Not What You Think",
    "Why Your Nose Runs When You Cry or Eat Hot Food",
    "Phantom Phone Vibrations — Your Body's Strangest Illusion",
    "Why You Lose Taste Sensation After Burning Your Tongue",
    "Why Your Voice Sounds Different in Recordings",
    "The Strange Reason Your Eyes See Afterimages",
    "Why Food Tastes Different When You Have a Cold",
    "Why You Hear Your Own Voice Differently Than Others Do",
    "The Reason You Smell Something That Isn't There",
    "Why Your Skin Crawls When Someone Touches You Unexpectedly",
    "Why You Can Feel Someone Staring at You",
    "The Reason Cold Water Feels colder Than Cold Air",
    "Why Your Brain Creates Phantom Sounds at Night",
    "Why You See Faces in Random Objects",
    "The Hidden Reason Music Gives You Goosebumps",
    "Why Your Eyes Water When You Eat Spicy Food",
    "The Science Behind Feeling a Lump That Isn't There",
    "Why You Hear a Loud Bang When Falling Asleep",
    "Why Colors Look Different Under Different Lights",
    "The Reason You Can't Smell Your Own Cologne",
    "Why Your Tongue Feels Weird After Eating Pineapple",
    "Why You See Floaters Drifting Across Your Vision",
    "The Reason You Feel a Phantom Vibration in Your Pocket",
    "Why Your Eyes Dilate When You See Something You Like",
    "The Strange Reason You Taste Metal in Your Mouth",
    "Why Your Nose Runs When It's Cold Outside",
    "The Science Behind Numbness in Your Fingers",

    # ── Dark Mystery & Medical Curiosities (Added August 2026) ──
    "Why you see a 'demon' during Sleep Paralysis",
    "Why your face distorts in the mirror (Troxler's Effect)",
    "The mystery of Exploding Head Syndrome",
    "The disease that stops you from ever sleeping again",
    "When your brain thinks your family are clones",
    "Why your brain forces you to see faces in shadows",
    "The mental glitch where you believe you are dead",
    "When your own hand acts without your permission",
    "Why your body violently twitches right before sleep",
    "The nightmare of remembering every second of your life",
    "The horror of not being able to recognize your own face",
    "The person who actually feels the physical pain of others",
    "The rare glitch where people see their own double",
    "When your brain makes the room feel miles long",
    "How your brain feels pain in a limb that isn't there",
    "Waking up with an accent from a country you never visited",
    "The scientific truth behind Near-Death Experiences",
    "The parasite that might be controlling your behavior",
    "The biological reason we are terrified of human-like faces",
    "The nightmare of being fully awake but unable to blink",
]


# -----------------------------------------------
# Dynamic topic generation: when the static pool
# runs low, call Groq LLM to generate fresh topics
# so the channel never repeats.
# -----------------------------------------------

_DYNAMIC_TOPIC_CACHE: list = []  # filled on first shortfall


def _generate_dynamic_topics(count: int = 50) -> List[str]:
    """Use the same Groq LLM the script generator uses to mint fresh,
    unique topic strings that fit the channel's dark-body-science niche.

    Called lazily — only when the static pool + trend pool are exhausted
    or fully excluded.  Returns an empty list on any failure so the
    pipeline gracefully falls back to the static pool.
    """
    try:
        import os
        from groq import Groq
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            return []
        client = Groq(api_key=api_key)
        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{
                "role": "user",
                "content": (
                    f"Generate exactly {count} unique, curiosity-driven YouTube Shorts "
                    "topic titles about the human body, brain, health, and science. "
                    "Each must be under 60 characters, sound like a real person talking "
                    "(use 'Your' or 'You'), and NOT use clickbait phrases like "
                    "'doctors don't want', 'shocking', 'you won't believe', or "
                    "'this will blow your mind'. Return ONLY a JSON array of strings."
                ),
            }],
            response_format={"type": "json_object"},
            temperature=0.9,
            max_tokens=2000,
        )
        import json
        data = json.loads(resp.choices[0].message.content)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for v in data.values():
                if isinstance(v, list):
                    return v
        return []
    except Exception as e:
        logger.warning(f"Dynamic topic generation failed: {e}")
        return []


# ============================================
# 2. HOOK FORMULAS — HONEST, NO CLICKBAIT
# YouTube 2026 penalizes: "Doctors don't want",
# "You won't believe", "This is real", etc.
# These hooks spark genuine curiosity instead.
# ============================================
HOOK_FORMULAS = [
    "This happens to your body every night... and you have no idea.",
    "Something in your body is happening without your permission.",
    "You've done this a million times and never asked why.",
    "Nobody told you this is happening inside you right now.",
    "This is the part of {topic} your biology teacher skipped.",
    "Scientists only figured this out about {topic} recently.",
    "Your body has been hiding this from you your whole life.",
    "This is why {topic} feels so unsettling once you know it.",
    "Most people go their entire life never knowing this about {topic}.",
    "There's a reason no one talks about {topic}.",
    "This is what happens inside when {topic} occurs.",
    "Every time {topic} happens, your body is trying to tell you something.",
    "The science behind {topic} is stranger than fiction.",
    "This is the real reason {topic} happens in your body.",
    "Here's what actually happens when {topic}.",
    "Your body does something wild during {topic}.",
    "The truth about {topic} is more interesting than you think.",
    "Most people never learn this about {topic}.",
    "This one fact about {topic} will change how you see yourself.",
    "What actually happens during {topic} is fascinating.",
    "Your body has a built-in response to {topic}.",
    "The science behind {topic} is finally making sense.",
    "Here's the part about {topic} nobody explains clearly.",
    "What your body does during {topic} is genuinely surprising.",
    "The reason behind {topic} is more complex than you think.",
]

# ============================================
# 3. TRANSITION HOOKS (For Scene-to-Scene Retention)
# ============================================
TRANSITION_HOOKS = [
    "but that's only half the story...",
    "and here's why that matters...",
    "here's where it gets really strange...",
    "and this is the part nobody tells you...",
    "but here's what's interesting...",
    "and that's when things get dark...",
    "but your body has a response...",
    "and this changes everything...",
    "but the real reason is surprising...",
    "and it gets even weirder...",
    "but here's the twist...",
    "and this is where it gets fascinating...",
]

# ============================================
# 4. PAIN POINTS (15+)
# ============================================
PAIN_POINTS = [
    "Worried something is wrong with your body",
    "Can't sleep because your mind won't shut off",
    "Feel anxious about random body symptoms",
    "Notice something about their body and can't explain it",
    "Feel like their body is a mystery even to themselves",
    "Get scared by symptoms they don't understand",
    "Wonder if what's happening to them is normal",
    "Feel disconnected from how their own body works",
    "Google symptoms late at night and spiral",
    "Feel like no one explains this stuff clearly",
    "Worry about aging and what it means for their body",
    "Feel helpless when their body doesn't cooperate",
    "Want to understand why their body reacts differently than others",
    "Feel ashamed of body functions they can't control",
    "Question whether their body is working properly",
]

# ============================================
# 5. CTAS — NATURAL, NO ENGAGEMENT BAIT
# YouTube 2026 penalizes: "like if", "comment 🤯",
# "tag someone", "smash like", etc.
# These sound like a real person ending a conversation.
# ============================================
CTAS = [
    "Follow for more facts like this.",
    "More science that surprises you — follow along.",
    "See you in the next one.",
    "Follow if you want to understand your body better.",
    "More coming — follow so you don't miss it.",
    "If this surprised you, there's more where that came from.",
    "Follow for the next one — it's just as wild.",
    # FIXED 2026-07-31: Removed bait CTA "Share this with someone..." -> matches \bshare (this|it|with)\b
    # and gets stripped by strip_bait(), leaving empty CTA. Replaced with bait-free.
    "Your body is weirder than you think — follow for daily proof.",
    "Follow for daily body science.",
    "Bookmark this for later — you'll want to remember it.",
    "Want more? Follow for the next deep dive.",
    "This channel explains the stuff nobody else does — follow.",
    "Follow along — new facts every day.",
    "The oddest body fact is tomorrow — follow so you catch it.",
    "Follow for the next body mystery explained.",
]

# ============================================
# 6. CATEGORY TAGS (SEO)
# ============================================
CATEGORY_TAGS = {
    "Brain": [
        "neuroscience", "brainfacts", "psychologyfacts", "mindblown",
        "brainscience", "humanbrain", "nervoussystem", "mentalhacks",
        "brainhealth", "neuroplasticity", "cognition", "memory",
    ],
    "Body": [
        "humanbody", "bodyfacts", "anatomy", "bodyparts", "humanfacts",
        "bodyawareness", "bodymystery", "yourbody", "physiology",
        "humananatomy", "bodyscience", "healthfacts",
    ],
    "Pain": [
        "bodysignals", "painscience", "bodywarning", "healthalert",
        "jointpain", "musclepain", "backpain", "headache",
        "chronicpain", "bodyhurts", "nervepain", "bodypain",
    ],
    "Sensory": [
        "sensoryscience", "visionfacts", "hearingfacts", "touchsense",
        "phantomvibration", "earsringing", "tastesmell", "bodysenses",
        "sensoryglitch", "weirdsenses", "braintricks", "sensoryfacts",
    ],
    "Mystery": [
        "mysteryscience", "weirdfacts", "creepyfacts", "unknownfacts",
        "darkscience", "bodysecrets", "themoreyouknow", "mindblowing",
        "scaryfacts", "unexplained", "paranormal",
    ],
    "Health": [
        "healthfacts", "bodyhacks", "sciencefacts", "healthscience",
        "medicalmystery", "humanhealth", "wellness", "healthtips",
        "wellnessjourney", "healthyliving",
    ],
}

# ============================================
# 7. BASE TAGS
# ============================================
BASE_TAGS = [
    "darkfacts", "facts", "shorts", "youtubeshorts", "science",
    "didyouknow", "mindblowing", "funfacts", "scaryfacts", "viral",
    "mystery", "unknown", "creepy", "interesting", "education",
]

# ============================================
# 8. CONSTANTS
# ============================================
TARGET_WORD_RANGE = (90, 120)
MAX_TAGS = 15
MAX_TITLE_LENGTH = 55
SCENES_PER_SCRIPT = 8  # Body Glitch 40-55 second series policy

# ============================================
# 9. MEDICAL RED FLAGS
# ============================================
_MEDICAL_ADVICE_RED_FLAGS = [
    "cure", "diagnose", "you have", "stop taking", "don't need a doctor",
    "instead of medication", "guaranteed to heal", "definitely means you have",
    "you should", "you must", "never go to the doctor", "ignore your doctor",
    "this is the only cure", "better than medicine", "replace your medication",
]

# ============================================
# 10. RETENTION-OPTIMIZED PROMPT GENERATION
# ============================================

def get_script_prompt_for_niche(
    topic: str,
    hook_preference: Optional[str] = None,
) -> str:
    """Compatibility wrapper for the unified script policy.

    Historically this module built a second, conflicting prompt (80–115 words,
    different hook limits and a forced dark tone). Keep the public function for
    callers, but delegate to ``script_generator`` so generation and validation
    always share exactly one contract.
    """
    from script_generator import _default_prompt
    return _default_prompt(topic)


def get_random_transition_hook() -> str:
    """Get a random transition hook for scene endings"""
    return random.choice(TRANSITION_HOOKS)


def get_transition_hooks(count: int = 3) -> List[str]:
    """Get multiple transition hooks"""
    return random.sample(TRANSITION_HOOKS, min(count, len(TRANSITION_HOOKS)))

# ============================================
# 11. CORE FUNCTIONS
# ============================================

def get_random_topic(exclude: Optional[List[str]] = None) -> str:
    """
    Picks a topic for the next video.

    Priority:
    1. Live trend-research topics (60% chance when available)
    2. Static DARK_TOPICS pool (fallback)
    3. Dynamic LLM-generated topics (when static pool exhausted)
    4. Skips recently used topics from exclude list
    """
    global _DYNAMIC_TOPIC_CACHE
    exclude_set = {t.strip().lower() for t in (exclude or []) if t}
    logger.debug(f"Excluding {len(exclude_set)} recent topics")

    # Try to get trending topics
    trending = []
    try:
        from trend_research import fetch_trending_topics
        trending = fetch_trending_topics()
        logger.debug(f"Fetched {len(trending)} trending topics")
    except ImportError:
        logger.debug("Trend research module not available")
    except Exception as e:
        logger.warning(f"Trend research failed: {e}")

    trend_candidates = [t for t in trending if t.strip().lower() not in exclude_set]

    if trend_candidates and random.random() < 0.6:
        chosen = random.choice(trend_candidates)
        logger.info(f"Selected trending topic: {chosen}")
        return chosen

    # Fallback to static pool
    static_candidates = [t for t in DARK_TOPICS if t.strip().lower() not in exclude_set]

    if static_candidates:
        chosen = random.choice(static_candidates)
        logger.info(f"Selected static topic: {chosen}")
        return chosen

    # Static pool exhausted → try dynamic LLM generation
    if not _DYNAMIC_TOPIC_CACHE:
        logger.info("Static topic pool exhausted — generating fresh topics via LLM...")
        _DYNAMIC_TOPIC_CACHE = _generate_dynamic_topics(50)
        if _DYNAMIC_TOPIC_CACHE:
            logger.info(f"Generated {len(_DYNAMIC_TOPIC_CACHE)} fresh topics from LLM")

    dynamic_candidates = [t for t in _DYNAMIC_TOPIC_CACHE if t.strip().lower() not in exclude_set]
    if dynamic_candidates:
        chosen = dynamic_candidates.pop(random.randrange(len(dynamic_candidates)))
        logger.info(f"Selected dynamic topic: {chosen}")
        return chosen

    # Last resort: allow a repeat from static pool
    logger.warning("All topic sources exhausted — allowing repeat from static pool")
    return random.choice(DARK_TOPICS)


def get_topic_category(topic: str) -> str:
    """Categorizes a topic into Brain, Body, Mystery, or Health."""
    topic_lower = topic.lower()

    brain_keywords = ['brain', 'mind', 'sleep', 'nerve', 'psych', 'memory', 'thought', 'conscious']
    body_keywords = ['heart', 'blood', 'lung', 'kidney', 'bone', 'organ', 'muscle', 'vein', 'artery']
    mystery_keywords = ['scary', 'secret', 'dark', 'mystery', 'hidden', 'unknown', 'creepy', 'weird']
    pain_keywords = ['pain', 'hurts', 'ache', 'sore', 'hurt', 'cramp', 'spasm', 'tingling', 'stiff', 'pins']
    sensory_keywords = ['ears ring', 'ringing', 'taste', 'smell', 'vision', 'floaters', 'afterimage', 'phantom', 'numbness', 'wrinkle', 'goosebump']

    def _has_word(words):
        return any(re.search(r'\b' + re.escape(w), topic_lower) for w in words)

    if _has_word(pain_keywords):
        return "Pain"
    elif _has_word(sensory_keywords):
        return "Sensory"
    elif _has_word(brain_keywords):
        return "Brain"
    elif _has_word(mystery_keywords):
        return "Mystery"
    elif _has_word(body_keywords):
        return "Body"
    else:
        return "Body"  # Default


def get_seo_tags(topic: str, category: str = "Body") -> List[str]:
    """Returns YouTube-optimized tags (max 15)."""
    topic_words = [
        w for w in topic.lower().split()
        if len(w) > 3 and w not in ['your', 'this', 'that', 'what', 'when']
    ]
    tags = topic_words[:5]
    tags.extend(CATEGORY_TAGS.get(category, []))
    related_phrases = [
        "human body", "science facts", "dark science",
        "body secrets", "mysterious facts", "human anatomy"
    ]
    tags.extend(related_phrases)
    tags.extend(BASE_TAGS)

    seen = set()
    result = []
    for tag in tags:
        clean = tag.strip().lower()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(tag)
        if len(result) >= MAX_TAGS:
            break

    return result


def generate_seo_tags(topic: str, category: str = "Body", title: str = "") -> List[str]:
    """Wrapper for get_seo_tags for compatibility."""
    return get_seo_tags(topic, category)


def validate_script_for_medical_accuracy(script_data: Dict) -> Dict:
    """Validates that script doesn't contain medical advice."""
    voiceover = script_data.get('voiceover', '')
    if not voiceover:
        voiceover = ' '.join([
            s.get('caption', '')
            for s in script_data.get('scenes', [])
            if isinstance(s, dict)
        ])

    lowered = voiceover.lower()
    flags = [phrase for phrase in _MEDICAL_ADVICE_RED_FLAGS if phrase in lowered]

    return {
        "valid": len(flags) == 0,
        "flags": flags,
        "has_red_flags": len(flags) > 0
    }


def auto_add_disclaimer(script_data: Dict) -> Dict:
    """Adds medical disclaimer to script."""
    disclaimer = "This video is for educational/entertainment purposes only and is not medical advice. Consult a doctor for any health concerns."

    script_data['cta'] = (
        script_data.get('cta', '') + " " + disclaimer
    ).strip()

    if 'description' in script_data:
        script_data['description'] = (
            script_data['description'] + " " + disclaimer
        ).strip()

    script_data['disclaimer_added'] = True
    logger.info("Added medical disclaimer to script")
    return script_data


# Emoji chosen by matching actual topic keywords
_TOPIC_EMOJI_MAP = [
    (['bone', 'bones', 'skeleton'], '🦴'),
    (['leg', 'legs', 'knee', 'knees'], '🦵'),
    (['ear', 'ears', 'hearing', 'sound'], '👂'),
    (['heart', 'blood', 'pulse', 'heartbeat'], '🫀'),
    (['immune', 'microbiome', 'bacteria', 'germ', 'germs', 'virus'], '🦠'),
    (['fingerprint', 'fingerprints', 'finger', 'fingers'], '🫆'),
    (['cold', 'chill', 'chills', 'temperature', 'fever'], '🥶'),
    (['eye', 'eyes', 'see', 'sight', 'blind spot'], '👁️'),
    (['muscle', 'muscles', 'strength', 'exercise'], '💪'),
    (['sleep', 'sleeping', 'night', 'nightmare', 'nightmares'], '😴'),
    (['brain', 'mind', 'memory', 'thought'], '🧠'),
]

# Was only [1F300-1FAFF, 2600-27BF, flags]. That misses common symbol-style
# "emoji" outside those blocks - stars (2B50), arrows (2190-21FF, 2B00-2BFF),
# geometric/media-control glyphs (25A0-25FF), and the variation-selector
# (FE0F) that often trails a symbol. When the LLM occasionally ignores the
# "no emojis" title rule and uses one of these, this pattern failed to strip
# it before a new topic emoji was appended -> title ended up with two
# emoji/symbols instead of one.
_EMOJI_PATTERN = re.compile(
    r"[\U0001F300-\U0001FAFF\u2600-\u27BF\u2190-\u21FF\u2B00-\u2BFF"
    r"\u25A0-\u25FF\U0001F1E6-\U0001F1FF\uFE0F]+\s*"
)


def _pick_topic_emoji(topic: str) -> str:
    """Pick the most relevant emoji for a topic."""
    topic_lower = topic.lower()
    for keywords, emoji in _TOPIC_EMOJI_MAP:
        if any(re.search(r'\b' + re.escape(kw) + r'\b', topic_lower) for kw in keywords):
            return emoji

    category = get_topic_category(topic)
    return {"Brain": "🧠", "Body": "🫀", "Mystery": "👁️", "Health": "🦠"}.get(category, "🫀")


def _make_seo_title(title: str, topic: str) -> str:
    """Enhances title for SEO while keeping under 55 chars.

    RETENTION NOTE (2026-08-14): the single-emoji suffix was a 100+ video
    machine template ("Why Your X 🫀") on this channel. 2026 inauthentic-
    content ranking suppresses template output, and a uniform title frame
    wrecks CTR novelty. ``TITLE_EMOJI_OFF=true`` (env) disables the emoji
    suffix entirely so titles go out as clean curiosity questions. The
    default is OFF (no emoji) because the data on this channel shows the
    emoji template coincides with its template demotion period; operators
    who still want the emoji can set ``TITLE_EMOJI_OFF=false``.
    """
    title = repair_mojibake(title)
    clean_title = _EMOJI_PATTERN.sub('', title, count=1).strip()
    _emoji_off = (os.environ.get("TITLE_EMOJI_OFF", "true").strip().lower()
                  in ("true", "1", "yes", "on"))
    if _emoji_off:
        # Strip any emoji the LLM smuggled in as well — plain text titles
        # perform and rank better on template-detection systems.
        clean_title = _EMOJI_PATTERN.sub('', clean_title).strip()
        return clean_title[:MAX_TITLE_LENGTH] if clean_title else topic[:MAX_TITLE_LENGTH]

    power_words = ["secret", "nobody", "never", "actually", "dark", "scary",
                   "real", "hidden", "warning", "shock", "fact", "truth"]
    if any(pw in clean_title.lower() for pw in power_words):
        return clean_title[:MAX_TITLE_LENGTH]

    emoji = _pick_topic_emoji(topic)

    enhanced = f"{clean_title} {emoji}"
    if len(enhanced) <= MAX_TITLE_LENGTH:
        return enhanced

    return clean_title[:MAX_TITLE_LENGTH]


# ---------------------------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------------------------

def make_seo_title(title: str, topic: str) -> str:
    """Enhance a video title for SEO (emoji + power-word detection).

    Public wrapper around the internal ``_make_seo_title``.
    """
    return _make_seo_title(title, topic)


# ============================================
# 12. UTILITY FUNCTIONS
# ============================================

def get_random_hook(topic: Optional[str] = None) -> str:
    """Get a random hook formula, optionally with topic."""
    hook = random.choice(HOOK_FORMULAS)
    if topic and "{topic}" in hook:
        hook = hook.format(topic=topic)
    return hook


def get_random_pain_point() -> str:
    """Get a random pain point."""
    return random.choice(PAIN_POINTS)


def get_random_cta() -> str:
    """Get a random CTA."""
    return random.choice(CTAS)


def get_category_tags(category: str) -> List[str]:
    """Get tags for a specific category."""
    return CATEGORY_TAGS.get(category, CATEGORY_TAGS["Body"])


def get_scene_count() -> int:
    """Get the optimal number of scenes for retention."""
    return SCENES_PER_SCRIPT

# ============================================
# 13. RETENTION ANALYSIS FUNCTIONS
# ============================================

def analyze_retention_potential(script_data: Dict) -> Dict:
    """Analyzes script for retention potential."""
    scenes = script_data.get('scenes', [])
    score = 0
    suggestions = []

    if len(scenes) == SCENES_PER_SCRIPT:
        score += 20
    else:
        suggestions.append(f"Optimal scene count is {SCENES_PER_SCRIPT}, currently {len(scenes)}")

    cliffhanger_count = 0
    for scene in scenes:
        caption = scene.get('caption', '')
        if any(word in caption.lower() for word in ['...', 'but', 'however', 'yet', 'still']):
            cliffhanger_count += 1

    cliffhanger_ratio = cliffhanger_count / len(scenes) if scenes else 0
    if 1 <= cliffhanger_count <= 2:
        score += 30
    elif cliffhanger_count > 2:
        suggestions.append(f"Too many forced cliffhangers ({cliffhanger_count}); use at most two")
    else:
        suggestions.append("Add one natural open loop after the hook")

    you_count = 0
    for scene in scenes:
        caption = scene.get('caption', '')
        you_count += caption.lower().count('you')

    if you_count >= len(scenes) * 2:
        score += 25
    else:
        suggestions.append("Use more 'YOU' language for personal connection")

    visual_quality = 0
    for scene in scenes:
        visual = scene.get('visual', '')
        if any(word in visual.lower() for word in ['cinematic', 'macro', 'close', 'dark', 'dramatic']):
            visual_quality += 1

    if visual_quality >= len(scenes) * 0.6:
        score += 25
    else:
        suggestions.append("Make visuals more CINEMATIC and DYNAMIC")

    return {
        'retention_score': min(100, score),
        'suggestions': suggestions,
        'cliffhanger_ratio': cliffhanger_ratio,
        'you_count': you_count,
        'visual_quality': visual_quality / len(scenes) if scenes else 0
    }

# ============================================
# 14. MAIN EXECUTION
# ============================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("="*60)
    print("RETENTION-OPTIMIZED NICHE STRATEGY TEST")
    print(f"Static topic pool: {len(DARK_TOPICS)} topics")
    print("="*60)

    print("\n1. Topic Selection:")
    for i in range(3):
        topic = get_random_topic()
        print(f"   - {topic}")

    print("\n2. Hooks (no clickbait):")
    for i in range(3):
        print(f"   - {get_random_hook('your brain')}")

    print("\n3. CTAs (natural, no engagement bait):")
    for i in range(3):
        print(f"   - {get_random_cta()}")

    print("\n" + "="*60)
    print("✅ NICHE STRATEGY MODULE READY!")
    print("="*60)
