from flask import Flask, render_template, request, redirect, url_for, session
from owlready2 import get_ontology
from pathlib import Path

# ---------- Paths ----------
HERE = Path(__file__).parent
OWL_PATH = HERE / "fractions_its.owl"

# ---------- Names ----------
N = {
    "Exercise": "Exercise",
    "Fraction": "Fraction",
    "Numerator": "Numerator",
    "Denominator": "Denominator",
    "SimplifiedFraction": "SimplifiedFraction",
    "Hint": "Hint",
    "SkillLevel": "SkillLevel",
    "about": "about",
    "hasNumerator": "hasNumerator",
    "hasDenominator": "hasDenominator",
    "hasSimplifiedForm": "hasSimplifiedForm",
    "hasHint": "hasHint",
    "hasSkillLevel": "hasSkillLevel",
    "promptText": "promptText",
    "hintText": "hintText",
    "numericalValue": "numericalValue",
    "expectedNumerator": "expectedNumerator",
    "expectedDenominator": "expectedDenominator",
}

LEVELS = ["Beginner", "Intermediate", "Advanced"]

app = Flask(__name__)
app.secret_key = "change-me-dev-key"

# ---------- Ontology helpers ----------
def onto_get(onto, name):
    try:
        return onto[name]
    except KeyError:
        return None

def load_ontology():
    if not OWL_PATH.exists():
        return None, f"OWL file not found at: {OWL_PATH}"
    try:
        onto = get_ontology(str(OWL_PATH)).load()
        return onto, None
    except Exception as e:
        return None, f"Error loading ontology: {e}"

def extract_exercise_payload(ex, onto):
    dp_prompt = N["promptText"]
    dp_num = N["numericalValue"]
    dp_en  = N["expectedNumerator"]
    dp_ed  = N["expectedDenominator"]
    op_about = N["about"]
    op_hn = N["hasNumerator"]
    op_hd = N["hasDenominator"]
    op_hs = N["hasSimplifiedForm"]
    op_hint = N["hasHint"]
    op_level = N["hasSkillLevel"]

    prompt = getattr(ex, dp_prompt, [""])[0] if hasattr(ex, dp_prompt) else ""

    level = None
    if hasattr(ex, op_level):
        lv_inds = getattr(ex, op_level)
        if lv_inds:
            level = lv_inds[0].name

    hints = []
    if hasattr(ex, op_hint):
        for h in getattr(ex, op_hint):
            txts = getattr(h, N["hintText"], [])
            if txts:
                hints.append(txts[0])

    frac = getattr(ex, op_about, [None])[0]
    if not frac:
        return None

    numi = getattr(frac, op_hn, [None])[0]
    deni = getattr(frac, op_hd, [None])[0]
    numv = getattr(numi, dp_num, [None])[0] if numi else None
    denv = getattr(deni, dp_num, [None])[0] if deni else None

    sfrac = getattr(frac, op_hs, [None])[0]
    expn  = getattr(sfrac, dp_en, [None])[0] if sfrac else None
    expd  = getattr(sfrac, dp_ed, [None])[0] if sfrac else None

    if None in (numv, denv, expn, expd):
        return None

    return {
        "name": ex.name,
        "prompt": prompt,
        "orig": (int(numv), int(denv)),
        "expected": (int(expn), int(expd)),
        "hints": hints,
        "level": level,
    }

def list_all_exercises(onto):
    Ex = onto_get(onto, N["Exercise"])
    if not Ex:
        return []
    payloads = []
    for ex in Ex.instances():
        data = extract_exercise_payload(ex, onto)
        if data:
            payloads.append(data)
    order = {lvl:i for i,lvl in enumerate(LEVELS)}
    payloads.sort(key=lambda d: (order.get(d.get("level"), 99), d["name"]))
    return payloads

# ---------- Checking ----------
def gcd(a, b):
    while b:
        a, b = b, a % b
    return abs(a)

def check_answer(u_num, u_den, o_num, o_den, e_num, e_den):
    if u_num == e_num and u_den == e_den:
        return True, "✅ Correct!", None
    if u_den == o_den and u_num*o_den == o_num*u_den and (u_num != o_num):
        return False, "You simplified only the numerator — divide both parts by the same number.", "Divide both numerator and denominator by the same factor."
    if u_num*o_den == o_num*u_den:
        if gcd(u_num,u_den) > 1:
            return False, "You can simplify further — try the greatest common factor.", "Try a bigger common factor (2, 3, 5, 7...)."
        return False, "Equivalent but unexpected — recheck your factors.", None
    if u_num == o_den and u_den == o_num:
        return False, "Careful! Don’t swap numerator and denominator.", "Numerator (top) comes first."
    return False, "Not quite. Which factor divides both parts?", "Use the same factor for top and bottom."

# ---------- Load ontology at startup ----------
ONTO, LOAD_ERR = load_ontology()
ALL_EX = list_all_exercises(ONTO) if ONTO else []
ALL_TOTAL = len(ALL_EX)

def filtered_list(level_label):
    if not level_label or level_label not in LEVELS:
        return ALL_EX
    return [e for e in ALL_EX if e["level"] == level_label]

def clamp_index(i, total):
    return max(0, min(i, max(0, total - 1)))

# ---------- Routes ----------
@app.route("/", methods=["GET", "POST"])
def index():
    session.setdefault("correct", 0)
    session.setdefault("attempts", 0)
    session.setdefault("answers", {})  # exercise name -> last typed answer

    if not ALL_TOTAL:
        return render_template(
            "index.html",
            prompt="(No exercises found)",
            feedback=LOAD_ERR or "Add Exercise individuals to the ontology.",
            hint=None,
            correct=False,
            idx=0, total=0,
            last_answer=None,
            stored_answer=None,
            hints=[],
            owl_path=str(OWL_PATH),
            levels=LEVELS, level=None,
            correct_count=session["correct"],
            tries=session["attempts"],
            accuracy=None,
        )

    level = request.args.get("level")
    ex_list = filtered_list(level)
    total = len(ex_list)
    if total == 0:
        ex_list = ALL_EX
        total = len(ex_list)
        level = None

    try:
        i = int(request.args.get("i", "0"))
    except ValueError:
        i = 0
    i = clamp_index(i, total)

    ex = ex_list[i]
    ex_name = ex["name"]
    prompt = ex["prompt"]
    (on, od) = ex["orig"]
    (en, ed) = ex["expected"]
    hints = ex["hints"]

    feedback = None
    hint = None
    correct = False
    last_answer = None

    if request.method == "POST":
        nav = request.form.get("nav")
        if nav == "reset":
            session["correct"] = 0
            session["attempts"] = 0
            session["answers"] = {}
            return redirect(url_for("index", i=0, level=level))
        if nav in ("next", "prev"):
            ni = (i + (1 if nav == "next" else -1)) % total
            return redirect(url_for("index", i=ni, level=level))

        ans = request.form.get("answer", "").strip()
        last_answer = ans
        answers = session.get("answers", {})
        answers[ex_name] = ans
        session["answers"] = answers

        session["attempts"] += 1
        try:
            a, b = ans.split("/", 1)
            a = int(a); b = int(b)
            correct, feedback, hint = check_answer(a, b, on, od, en, ed)
            if correct:
                session["correct"] += 1
            if not correct and not hint and hints:
                hint = hints[0]
        except Exception:
            feedback = "Please enter your answer like 1/2"
            correct = False

    # Prefill + auto-show "Correct!" on GET when stored answer is correct
    stored = session.get("answers", {}).get(ex_name)
    if request.method == "GET" and stored:
        try:
            a, b = stored.split("/", 1)
            a, b = int(a), int(b)
            is_ok, fb, h = check_answer(a, b, on, od, en, ed)
            if is_ok:
                feedback = "✅ Correct!"
                correct = True
        except Exception:
            pass

    accuracy = None
    if session["attempts"] > 0:
        accuracy = round(100 * session["correct"] / session["attempts"])

    return render_template(
        "index.html",
        prompt=prompt,
        feedback=feedback,
        hint=hint,
        correct=correct,
        idx=i,
        total=total,
        last_answer=last_answer,
        stored_answer=stored,
        hints=hints,
        owl_path=str(OWL_PATH),
        levels=LEVELS,
        level=level,
        correct_count=session["correct"],
        tries=session["attempts"],
        accuracy=accuracy,
    )

if __name__ == "__main__":
    print(f"Loaded {ALL_TOTAL} exercises from {OWL_PATH}")
    app.run(debug=True)
