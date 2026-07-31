# SKILLOR — last run kyun fail hua (aur kya fix kiya)

**Failed run:** [30625527563](https://github.com/jashaidaslamhfd/SKILLOR/actions/runs/30625527563) — "SKILLOR - YouTube Shorts Automation (US)", 31 July 2026, 7m53s
**Final error:**

```
RuntimeError: All 3 script-generation attempts failed mandatory gates.
Last error: best candidate rejected: hook=55/80
```

Workflow ne 3 baar retry kiya, teeno baar fail — koi video upload nahi hua.

**Ahem baat:** na Groq API down thi, na secrets missing thay, na model kharab likh raha tha.
Repo ke andar **do gates aapas mein contradict kar rahe thay**, is liye script kabhi pass ho hi
nahi sakti thi. Ye 2 din se aa raha tha (runs 30560416469, 30507160752, 30498626723 bhi isi
wajah se fail huay).

---

## Root cause 1 — Trimmer aur validator alag-alag ceiling laga rahe thay 🔴

`_trim_to_word_limit()` jaan-boojh kar poora jumla rakhta hai agar wo budget se sirf
`_OVERSHOOT_GRACE_WORDS` (= 2) lafz upar ho — kyunki beech se kaatne par caption tut jata hai
("Your calf locks up in."). Lekin `_validate_script()` uske foran baad **raw budget** check kar
raha tha:

```
trimmer : 16-word jumla bachaya  (15 + 2 grace = allowed)
validator: "Scene 8 has 16 words (maximum 15)"  ❌ reject
```

Yaani grace wali branch **kabhi kaam kar hi nahi sakti thi** — jo caption trimmer bachata, wo
agli line par reject ho jata. CI log mein bilkul yehi dikha:

```
Scene 8 has 17 words (maximum 15)
Scene 8 has 19 words (maximum 15)
Scene 7 has 16 words (maximum 15)
```

**Fix:** naya `effective_word_ceiling()` — ab dono taraf ek hi constant se ceiling aati hai.
Jo caption waqai bohot lamba ho wo ab bhi reject hota hai.

## Root cause 2 — Hook scorer inflected English parh hi nahi sakta tha 🔴

`_CONCRETE_RE` stem ke baad sirf **appended** letters match karta tha (`twitch` → `twitching` ✓).
Lekin English vowel-suffix se pehle trailing "e" gira deti hai, is liye:

| word | pehle | ab |
|---|---|---|
| shake → **shaking** | ❌ miss | ✅ |
| freeze → **freezing** | ❌ miss | ✅ |
| tingle → **tingling** | ❌ miss | ✅ |
| tremble → **trembling** | ❌ miss | ✅ |
| memory → **memories** | ❌ miss | ✅ |

Run ka topic tha **"your voice shaking when speaking in front of crowds"** — `shake` list mein
maujood tha, magar `shaking` match nahi hua. Hook ne 25-point "specificity" check khoya, aur
**55/100** par atak gaya. Gate 80 hai → wahi `hook=55/80` jo traceback mein hai.

Model theek likh raha tha; scorer parh nahi pa raha tha.

**Fix:** drop-e aur y/ies inflection patterns add kiye — itne tight ke `ache` ab bhi `achieve`
par match nahi karta. Same hook ab **55 → 100**.

---

## Baaki issues jo isi tehqeeq mein mile

| # | Issue | Asar |
|---|---|---|
| 3 | `scheduler.ranked_peak_times()` `self._learned_slot_weights()` call karta tha. Koi caller agar us staticmethod ko plain function se badal de, to har slot lookup `takes 0 positional arguments but 1 was given` throw karta tha | Instagram chupke se peak slot chhod kar "abhi post karo" par chala jata tha |
| 4 | `uploader.py` mein peak slots ki **doosri hardcoded copy** thi jo drift kar chuki thi (abhi bhi 21:30, jab ke scheduler 18:30 par ja chuka tha) | Ek hi video ka YouTube `publishAt` aur Instagram post do alag waqt par aim kar rahe thay |
| 5 | Commit `7551743` ka mis-indented comment; `,` par khatam hone wale caption mein period lagne se `"your foot tingles,."` banta tha | SRT aur burned-in captions mein ganda punctuation |
| 6 | 1 unused import, 1 unused variable, 6 f-strings bina placeholder | Code quality (pyflakes ab bilkul clean) |

---

## Tests

```
pehle : 159 pass
ab    : 170 pass, pyflakes clean
```

3 nayi regression classes — **har ek ko fix hatakar verify kiya gaya ke wo waqai fail hoti hai**,
aur wahi CI error dobara reproduce hua (`Scene 8 has 16 words (maximum 15)`).

- `TrimmerAndValidatorAgreeTests` — trimmer jo caption bachaye, validator use qubool kare
- `HookScorerMorphologyTests` — inflected words + "achieve" wala false-positive guard
- `PublishSlotConsistencyTests` — uploader aur scheduler ke slots hamesha match karein

Ek extra invariant test: word grace kabhi `hook_enforcement_seconds` (3.78s) se aage nahi ja
sakta. Abhi sab se lamba allowed hook 9 words = **3.44s** — mehfooz. Is se ye nahi ho sakta ke
validator aisi script pass kar de jise renderer baad mein reject kar de.

---

## Ek cheez jo maine jaan bujh kar nahi chhui

`main.py` ka "best candidate rejected" wala design — jab hook gate fail ho to ye upload skip kar
deta hai. Ye **jaan boojh kar aisa hai** (comment: *"A missed upload is safer for channel
retention and trust than a weak Short"*), aur ab jab dono root causes theek ho gaye hain to ye
gate normal scripts ko block nahi karega. Agar aap chahen ke gate fail hone par bhi video jaye
(ya `MIN_HOOK_SCORE` 80 se kam ho), to bataiye — wo policy ka faisla hai, bug nahi.
