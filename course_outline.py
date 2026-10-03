"""Create an honest, editable storyboard from a new course brief.

This is a planning scaffold, not AI-written instruction. Narration stays empty
until a human supplies accurate teaching, examples, and pronunciation.
"""

from __future__ import annotations

from engine import LANGUAGES


COPY = {
    "en-US": {
        "intro": "Introduction", "intro_scenes": ("The learner's challenge", "The result to work toward"),
        "defaults": ("Understand the fundamentals", "Follow the process", "Practice with an example"),
        "lesson": ("What it is and why it matters", "How to do it: a practical example", "Mistakes and best practices"),
        "finish": "Apply what you learned", "finish_scenes": ("A useful checklist", "Your next action"),
        "topic": "Topic", "audience": "Audience", "goal": "Learning goal",
        "research": "Add verified facts, a real example, and a clear visual demonstration.",
        "process": "Show the steps on screen. Add a worked example and explain the result.",
        "mistakes": "Show a realistic mistake, explain why it fails, then show the better method.",
    },
    "ur-PK": {
        "intro": "تعارف", "intro_scenes": ("سیکھنے والے کا مسئلہ", "مطلوبہ نتیجہ"),
        "defaults": ("بنیادی باتیں سمجھیں", "عملی طریقہ اپنائیں", "مثال کے ساتھ مشق کریں"),
        "lesson": ("یہ کیا ہے اور کیوں اہم ہے", "عملی طریقہ اور مثال", "عام غلطیاں اور بہتر طریقہ"),
        "finish": "سیکھی ہوئی بات پر عمل", "finish_scenes": ("عملی چیک لسٹ", "اگلا قدم"),
        "topic": "موضوع", "audience": "سیکھنے والے", "goal": "سیکھنے کا مقصد",
        "research": "درست معلومات، حقیقی مثال اور واضح بصری مظاہرہ شامل کریں۔",
        "process": "اسکرین پر مراحل، ایک مکمل مثال اور اس کا نتیجہ دکھائیں۔",
        "mistakes": "عام غلطی، اس کا اثر اور بہتر طریقہ واضح کریں۔",
    },
    "de-DE": {
        "intro": "Einführung", "intro_scenes": ("Die Herausforderung", "Das Lernziel"),
        "defaults": ("Grundlagen verstehen", "Den Ablauf anwenden", "An einem Beispiel üben"),
        "lesson": ("Was es ist und warum es wichtig ist", "So geht es: ein praktisches Beispiel", "Fehler und bewährte Methoden"),
        "finish": "Das Gelernte anwenden", "finish_scenes": ("Praktische Checkliste", "Der nächste Schritt"),
        "topic": "Thema", "audience": "Zielgruppe", "goal": "Lernziel",
        "research": "Geprüfte Fakten, ein echtes Beispiel und eine klare Visualisierung ergänzen.",
        "process": "Schritte zeigen und ein Beispiel mit Ergebnis durcharbeiten.",
        "mistakes": "Einen typischen Fehler und die bessere Vorgehensweise zeigen.",
    },
    "ar-SA": {
        "intro": "مقدمة", "intro_scenes": ("تحدي المتعلم", "النتيجة المطلوبة"),
        "defaults": ("فهم الأساسيات", "اتباع الخطوات", "التدرب بمثال"),
        "lesson": ("ما هو ولماذا يهم", "كيف تطبقه مع مثال عملي", "الأخطاء والممارسات الجيدة"),
        "finish": "طبّق ما تعلمته", "finish_scenes": ("قائمة تحقق عملية", "خطوتك التالية"),
        "topic": "الموضوع", "audience": "الجمهور", "goal": "هدف التعلم",
        "research": "أضف حقائق موثوقة ومثالاً حقيقياً وشرحاً مرئياً واضحاً.",
        "process": "اعرض الخطوات على الشاشة ومثالاً كاملاً ونتيجته.",
        "mistakes": "اعرض خطأ شائعاً وأثره ثم الطريقة الأفضل.",
    },
}


def build_outline(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("Enter a course brief.")
    language = raw.get("language", "")
    if language not in LANGUAGES:
        raise ValueError("Choose one of the supported course languages.")
    fields = [raw.get("topic"), raw.get("audience"), raw.get("goal")]
    if any(not isinstance(value, str) for value in fields):
        raise ValueError("Enter a topic, audience and learning goal.")
    topic, audience, goal = (value.strip() for value in fields)
    if not 1 <= len(topic) <= 85 or not 1 <= len(audience) <= 85 or not 1 <= len(goal) <= 85:
        raise ValueError("Enter a topic, audience and learning goal (up to 85 characters each).")
    supplied = raw.get("sections", [])
    if not isinstance(supplied, list) or len(supplied) > 8 or any(not isinstance(value, str) for value in supplied):
        raise ValueError("Use up to eight lesson sections.")
    sections = [value.strip() for value in supplied if value.strip()]
    if any(len(value) > 85 for value in sections):
        raise ValueError("Keep each lesson section under 85 characters.")
    copy = COPY[language]
    sections = sections or list(copy["defaults"])
    scenes = []

    def add(chapter: str, heading: str, visual: str, points: list[str], note: str) -> None:
        scenes.append({
            "chapter": chapter, "chapter_start": not scenes or scenes[-1]["chapter"] != chapter,
            "heading": heading, "narration": "", "points": points,
            "visual_type": visual, "asset": "", "production_note": note,
        })

    add(copy["intro"], copy["intro_scenes"][0], "comparison",
        [copy["topic"], topic, copy["audience"], audience], copy["research"])
    add(copy["intro"], copy["intro_scenes"][1], "flow",
        [copy["goal"], goal], copy["process"])
    for section in sections:
        what, how, mistakes = copy["lesson"]
        add(section, what, "diagram", [section], copy["research"])
        add(section, how, "flow", [section], copy["process"])
        add(section, mistakes, "comparison", [section], copy["mistakes"])
    add(copy["finish"], copy["finish_scenes"][0], "checklist", sections[:5], copy["process"])
    add(copy["finish"], copy["finish_scenes"][1], "flow", [goal], copy["process"])
    return {
        "name": topic,
        "versions": {language: {
            "title": topic, "voice": LANGUAGES[language]["voices"][0]["id"],
            "scenes": scenes, "reviewed": False,
        }},
    }
