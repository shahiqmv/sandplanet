"""The content of the safety induction, SP-HSE-F01 Rev 0 (owner 2026-10-26).

Transcribed from the approved form, English and Bengali, in the form's order.
A new revision of the form is a new constant and a new FORM_REV, so a session
always prints — and records — the revision it was given from.
"""
FORM_REV = "F01 Rev 0"

TITLE_BN = "সেফটি ইনডাকশন প্রশিক্ষণ"
NO_START = ("No one starts work on site until this induction is completed "
            "and signed.",
            "এই ইনডাকশন সম্পন্ন ও স্বাক্ষর না করা পর্যন্ত কেউ সাইটে কাজ শুরু "
            "করতে পারবে না।")
DECLARATION = (
    "I confirm that this induction was explained to me in a language I "
    "understand, and that I have understood and will strictly follow all the "
    "safety rules above.",
    "আমি নিশ্চিত করছি যে এই ইনডাকশন আমাকে আমার বোধগম্য ভাষায় বুঝিয়ে বলা "
    "হয়েছে, এবং আমি উপরের সমস্ত সুরক্ষা নিয়ম বুঝতে পেরেছি ও কঠোরভাবে মেনে "
    "চলতে সম্মত হয়েছি।")
FILING = ("File the signed original on site and send a scan to HR, Head "
          "Office. Upload the signed copy to Planet: it records each "
          "participant's induction.")

# (no, English title, Bengali title, [(English, Bengali), ...])
TOPICS = [
    ("01", "Personal Protective Equipment (PPE)",
     "ব্যক্তিগত সুরক্ষা সরঞ্জাম (PPE)", [
         ("PPE must be worn as required at all times on site.",
          "নির্মাণ সাইটে প্রবেশের সময় প্রয়োজন অনুযায়ী PPE পরতে হবে।"),
         ("General PPE: Safety Helmet, Safety Vest, Safety Shoes.",
          "সাধারণ PPE: সেফটি হেলমেট, সেফটি ভেস্ট, সেফটি জুতা।"),
         ("Work at height: Full Body Harness.",
          "উচ্চতায় কাজের PPE: বডি হারনেস।"),
         ("Working over water or on boats: Life Jacket.",
          "পানির উপর বা নৌকায় কাজ: লাইফ জ্যাকেট।"),
         ("Chemical work: Rubber Gloves, Mask, Safety Goggles.",
          "রাসায়নিক কাজে PPE: রাবার গ্লাভস, মাস্ক, সেফটি গগলস।"),
         ("Hot work: Welding Gloves, Welding Face Shield, Welding Clothing.",
          "হট ওয়ার্কের PPE: ওয়েল্ডিং গ্লাভস, ওয়েল্ডিং ফেস শিল্ড, ওয়েল্ডিং "
          "পোশাক।"),
         ("Noise: Ear Plugs.", "শব্দজনিত ঝুঁকির PPE: ইয়ার প্লাগ।"),
         ("Grouting and concrete: Safety Glasses, Dust Mask.",
          "গ্রাউটিং ও কংক্রিট কাজের PPE: সেফটি গ্লাস, ডাস্ট মাস্ক।"),
         ("Lost or damaged PPE must be reported for replacement.",
          "হারানো বা নষ্ট PPE প্রতিস্থাপনের জন্য জানাতে হবে।"),
     ]),
    ("02", "General Safety Rules", "সাধারণ নিরাপত্তা বিধি", [
        ("Do not use equipment, appliances or tools outside the scope of "
         "your duties.",
         "আমার দায়িত্বের আওতার বাইরে কোনো সরঞ্জাম, যন্ত্রপাতি বা টুল ব্যবহার "
         "করা কঠোরভাবে নিষিদ্ধ।"),
        ("Do not report for work after consuming alcohol or drugs.",
         "মদ বা মাদক গ্রহণের পর কাজে উপস্থিত হওয়া যাবে না।"),
        ("Do not remove scaffolding, safety barriers or safety signs without "
         "permission.",
         "অনুমতি ছাড়া সাইটের স্ক্যাফোল্ডিং, সুরক্ষা ব্যবস্থা ও নিরাপত্তা চিহ্ন "
         "খুলে ফেলা কঠোরভাবে নিষিদ্ধ।"),
        ("Do not damage site facilities, equipment or project property.",
         "সাইটের স্থাপনা, সরঞ্জাম বা প্রকল্পের অন্যান্য সম্পত্তি ইচ্ছাকৃতভাবে "
         "ক্ষতিগ্রস্ত করা যাবে না।"),
        ("No smoking in the work area.", "কাজের এলাকায় ধূমপান নিষিদ্ধ।"),
        ("No mobile phones in the work area.",
         "কাজের এলাকায় মোবাইল ফোন ব্যবহার করা যাবে না।"),
        ("No fighting.", "মারামারি করা যাবে না।"),
        ("No sleeping on site.", "সাইটে ঘুমানো যাবে না।"),
        ("No slippers or shorts.", "স্লিপার বা শর্টস পরা যাবে না।"),
        ("Theft is strictly prohibited.", "চুরি করা কঠোরভাবে নিষিদ্ধ।"),
        ("Follow the site safety management system at all times.",
         "সাইটের নিরাপত্তা ব্যবস্থাপনা মেনে চলতে হবে এবং নিরাপত্তা "
         "ব্যবস্থাপনা সিস্টেম অনুসরণ করতে হবে।"),
    ]),
    ("03", "Resort & Public Conduct",
     "রিসোর্ট ও জনসাধারণের সাথে আচরণ", [
         ("Follow all instructions from the resort (client) management and "
          "report any changes immediately.",
          "রিসোর্ট (ক্লায়েন্ট) ম্যানেজমেন্টের দেওয়া সব নির্দেশনা অনুসরণ করতে "
          "হবে এবং কোনো পরিবর্তন হলে তাৎক্ষণিকভাবে জানাতে হবে।"),
         ("Stay out of guest areas unless authorised. Be polite and discreet "
          "near guests.",
          "অনুমতি ছাড়া অতিথিদের এলাকায় যাওয়া যাবে না। অতিথিদের কাছে ভদ্র ও "
          "সংযত থাকতে হবে।"),
         ("Protect wildlife, vegetation and the environment.",
          "বন্যপ্রাণী সুরক্ষা, জঙ্গল ও পরিবেশের নিরাপত্তা নিশ্চিত করতে হবে।"),
         ("Comply with local laws and regulations.",
          "স্থানীয় আইন ও বিধিবিধান মেনে চলতে হবে।"),
         ("Respect local customs and culture.",
          "স্থানীয় রীতি-নীতি ও সংস্কৃতির প্রতি সম্মান দেখাতে হবে।"),
         ("Do not leave the accommodation at night without permission.",
          "রাতে অনুমতি ছাড়া বাইরে যাওয়া যাবে না।"),
         ("Do not take part in demonstrations.",
          "কোনো বিক্ষোভে অংশগ্রহণ করা কঠোরভাবে নিষিদ্ধ।"),
         ("Do not get into conflicts with outsiders.",
          "বহিরাগতদের সঙ্গে কোনো বিরোধে জড়ানো যাবে না।"),
     ]),
    ("04", "Emergency Preparedness & Assembly Point",
     "জরুরি প্রস্তুতি পরিকল্পনা ও সমাবেশস্থল", [
         ("In an emergency, follow site personnel and gather at the assembly "
          "point.",
          "জরুরি অবস্থায় সাইটের দায়িত্বপ্রাপ্ত ব্যক্তিদের নির্দেশনা মেনে "
          "নির্ধারিত জরুরি সমাবেশস্থলে একত্রিত হতে হবে।"),
         ("Electric shock: cut the power first. If you cannot, separate the "
          "person from the wire with a wooden stick or other insulated tool.",
          "বিদ্যুৎস্পৃষ্ট হলে প্রথমে বিদ্যুৎ সংযোগ বন্ধ করতে হবে। সময়মতো "
          "বিদ্যুৎ বন্ধ করা সম্ভব না হলে কাঠের লাঠি বা অন্য কোনো ইনসুলেটেড "
          "সরঞ্জাম দিয়ে তার আলাদা করতে হবে।"),
         ("Fire you cannot put out: evacuate calmly by the safe route.",
          "আগুন নেভানো সম্ভব না হলে আতঙ্কিত না হয়ে দ্রুত নিরাপদ পথে সরে যেতে "
          "হবে।"),
         ("Heat stroke: move the person to a cool place, loosen tight "
          "clothing and wipe the body with a wet towel.",
          "হিট স্ট্রোক হলে ব্যক্তিকে ঠান্ডা স্থানে নিয়ে যেতে হবে, আঁটসাঁট "
          "পোশাক ঢিলা/খুলে দিতে হবে এবং ভেজা তোয়ালে দিয়ে শরীর মুছে দিতে হবে।"),
         ("If a rod or sharp object pierces the body, do not remove it. Keep "
          "it still and wait for help.",
          "লোহার রড, কাঠি বা অন্য কোনো ধারালো বস্তু শরীরে ঢুকে গেলে তা বের "
          "করা যাবে না; বস্তুটি স্থির রেখে উদ্ধারকারী দলের জন্য অপেক্ষা করতে "
          "হবে।"),
         ("If you feel unwell, stop work and tell the engineer on duty.",
          "কাজের সময় কোনো অসুস্থতা বা অস্বস্তি হলে কাজ বন্ধ করে ডিউটিতে "
          "থাকা ইঞ্জিনিয়ারকে জানাতে হবে।"),
         ("Report any injury immediately to the site engineer, safety "
          "officer and supervisor.",
          "কেউ আহত হলে চিকিৎসার জন্য তাৎক্ষণিকভাবে সাইটের ইঞ্জিনিয়ার, সেফটি "
          "অফিসার ও সুপারভাইজারকে জানাতে হবে।"),
     ]),
    ("05", "Key Work Risks", "প্রাসঙ্গিক কাজের ঝুঁকি", [
        ("Working over water or on boats: risk of drowning, falls and slips. "
         "Life jacket is mandatory during boat transfers. Use safe access.",
         "পানির উপর / নৌকায় কাজ: ডুবে যাওয়া, পড়ে যাওয়া ও পিছলে যাওয়ার ঝুঁকি "
         "রয়েছে। লাইফ জ্যাকেট পরতে হবে এবং নিরাপদ প্রবেশ/বের হওয়ার পথ "
         "ব্যবহার করতে হবে।"),
        ("Diving and underwater work: only trained and authorised divers. "
         "Follow approved diving and emergency procedures.",
         "ডাইভিং / পানির নিচে কাজ: শুধুমাত্র প্রশিক্ষিত ও অনুমোদিত ডাইভাররা "
         "পানির নিচে কাজ করতে পারবেন। অনুমোদিত ডাইভিং ও জরুরি পদ্ধতি অনুসরণ "
         "করতে হবে।"),
        ("Working at height: use approved scaffolding, guardrails and fall "
         "protection.",
         "উচ্চতায় কাজ: পড়ে যাওয়ার ঝুঁকি রয়েছে। অনুমোদিত স্ক্যাফোল্ডিং, "
         "গার্ডরেল ও ফল-প্রোটেকশন ব্যবহার করতে হবে।"),
        ("Lifting: keep clear of suspended loads and follow the lifting "
         "plan.",
         "লিফটিং অপারেশন: মালামাল পড়ে যাওয়া ও চাপা পড়ার ঝুঁকি রয়েছে। ঝুলন্ত "
         "লোড থেকে দূরে থাকতে হবে এবং লিফটিং প্ল্যান অনুসরণ করতে হবে।"),
        ("Fire and electrical: follow hot-work rules, use inspected "
         "equipment, keep extinguishers ready.",
         "আগুন ও বৈদ্যুতিক ঝুঁকি: হট-ওয়ার্কের নিয়ম অনুসরণ করতে হবে, "
         "পরিদর্শিত বৈদ্যুতিক সরঞ্জাম ব্যবহার করতে হবে এবং ফায়ার "
         "এক্সটিংগুইশার প্রস্তুত রাখতে হবে।"),
        ("Tools and machinery: trained operators only. Keep exclusion "
         "zones.",
         "টুলস ও মেশিনারি: শুধুমাত্র প্রশিক্ষিত কর্মীরা সরঞ্জাম পরিচালনা করতে "
         "পারবেন এবং নিষিদ্ধ/নিরাপত্তা এলাকা বজায় রাখতে হবে।"),
        ("Weather and sea: stop work in unsafe wind, waves or lightning.",
         "আবহাওয়া / সমুদ্রের অবস্থা: ঝুঁকিপূর্ণ বাতাস, ঢেউ, বজ্রপাত বা খারাপ "
         "আবহাওয়ায় কাজ বন্ধ করতে হবে।"),
        ("Environment: keep fuel, chemicals, concrete, waste and debris out "
         "of the lagoon.",
         "পরিবেশ সুরক্ষা: জ্বালানি, রাসায়নিক, কংক্রিট, বর্জ্য ও ধ্বংসাবশেষ যেন "
         "লেগুনে প্রবেশ না করে তা নিশ্চিত করতে হবে।"),
        ("Stop work: anyone may stop work if conditions are unsafe. Report to "
         "the supervisor or safety officer immediately.",
         "জরুরি অবস্থা ও কাজ বন্ধ: কোনো অনিরাপদ অবস্থা শনাক্ত হলে কাজ বন্ধ "
         "করে তাৎক্ষণিকভাবে সুপারভাইজার/HSE টিমকে জানাতে হবে।"),
    ]),
    ("06", "Disciplinary Rules", "শৃঙ্খলা / নিয়মলঙ্ঘনের বিধি", [
        ("Rule breaches lead to graded action: recorded verbal warning, first "
         "written warning, final written warning, removal from site.",
         "নিয়ম লঙ্ঘনের জন্য ধাপে ধাপে ব্যবস্থা নেওয়া হবে: মৌখিক সতর্কীকরণ, "
         "প্রথম লিখিত সতর্কীকরণ, চূড়ান্ত লিখিত সতর্কীকরণ, সাইট থেকে অপসারণ।"),
        ("Do not touch, damage or step on coral. No fishing or harming marine "
         "life in the lagoon.",
         "কোরাল স্পর্শ করা, ক্ষতি করা বা তার উপর পা দেওয়া যাবে না এবং লেগুনে "
         "মাছ ধরা বা সামুদ্রিক জীবনের ক্ষতি করা কঠোরভাবে নিষিদ্ধ।"),
        ("Assaulting or threatening anyone on site means immediate removal "
         "from site and may be reported to the police.",
         "সাইটে কাউকে মারধর বা হুমকি দিলে সঙ্গে সঙ্গে সাইট থেকে অপসারণ করা "
         "হবে এবং পুলিশে জানানো হতে পারে।"),
        ("Working under alcohol or drugs, fighting or theft means immediate "
         "removal from site.",
         "মদ বা মাদক গ্রহণ করে কাজ, মারামারি বা চুরিতে জড়িত কাউকে সঙ্গে সঙ্গে "
         "সাইট থেকে অপসারণ করা হবে।"),
    ]),
]
TOPIC_NOS = [t[0] for t in TOPICS]
