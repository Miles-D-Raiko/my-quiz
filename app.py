import streamlit as st
import json
from datetime import datetime
import time
import random
import pymongo
from pymongo.errors import DuplicateKeyError

# ───────────────────────────────────────────────
# MongoDB Helpers (using st.secrets)
# ───────────────────────────────────────────────

@st.cache_resource
def get_mongo_client():
    try:
        uri = st.secrets.mongo.uri
    except (KeyError, AttributeError):
        st.error("""
MongoDB connection string not found in secrets.
Please go to Streamlit Cloud → your app → Secrets (or create .streamlit/secrets.toml locally)
and add:
[mongo]
uri = "mongodb+srv://<username>:<password>@<cluster>.mongodb.net/?retryWrites=true&w=majority"
db_name = "NextgenDev"
collection_name = "quizzes"
        """)
        st.stop()

    try:
        client = pymongo.MongoClient(uri)
        client.admin.command('ping')  # test connection
        return client
    except Exception as e:
        st.error(f"Failed to connect to MongoDB:\n{str(e)}\n\n"
                 "Common fixes:\n"
                 "• Check username/password\n"
                 "• Make sure your IP is allowed in Atlas Network Access\n"
                 "• Verify the connection string includes ?retryWrites=true&w=majority")
        st.stop()


@st.cache_resource(ttl=1800)  # 30 minutes
def get_quizzes_collection():
    client = get_mongo_client()
    db_name = st.secrets.mongo.get("db_name", "NextgenDev")
    coll_name = st.secrets.mongo.get("collection_name", "quizzes")
    
    db = client[db_name]
    coll = db[coll_name]

    # Ensure unique index on quiz_title
    try:
        coll.create_index("quiz_title", unique=True, background=True)
    except:
        pass  # index probably already exists

    return coll


def load_quizzes():
    """Load all quizzes from MongoDB into session state"""
    coll = get_quizzes_collection()
    st.session_state.quizzes.clear()
    try:
        for doc in coll.find({}, {"_id": 0}):
            title = doc.get("quiz_title")
            if title:
                st.session_state.quizzes[title] = doc
    except Exception as e:
        st.error(f"Could not load quizzes from MongoDB: {e}")


def save_quiz(title: str, data: dict):
    """Upsert quiz document by quiz_title"""
    coll = get_quizzes_collection()
    data = data.copy()
    data["quiz_title"] = title  # enforce consistency
    
    try:
        coll.replace_one(
            {"quiz_title": title},
            data,
            upsert=True
        )
        st.success(f"Quiz **{title}** saved/updated.")
        load_quizzes()  # refresh in-memory list
    except DuplicateKeyError:
        st.error("A quiz with this title already exists.")
    except Exception as e:
        st.error(f"Failed to save quiz: {e}")


def delete_quiz(title: str):
    coll = get_quizzes_collection()
    try:
        result = coll.delete_one({"quiz_title": title})
        if result.deleted_count == 1:
            st.success(f"Quiz **{title}** deleted.")
            if st.session_state.get("selected_quiz") == title:
                st.session_state.selected_quiz = None
            load_quizzes()
            st.rerun()
        else:
            st.warning(f"Quiz '{title}' not found in database.")
    except Exception as e:
        st.error(f"Delete failed: {e}")

# ───────────────────────────────────────────────
# Session State Initialization
# ───────────────────────────────────────────────

defaults = {
    'quizzes': {},
    'selected_quiz': None,
    'user_answers': {},
    'show_answers': False,
    'score': None,
    'quiz_start_time': None,
    'time_limit_minutes': None,
    'timer_expired': False,
    'reveal_correct_answers': False,
    'selected_departments': [],
    'selected_levels': [],
    'selected_semesters': [],
    'selected_weeks': [],
    'selected_categories': [],
    'admin_logged_in': False,
    'shuffled_questions': None,
    'option_shuffles': {},
    'edit_quiz_title': None,
    'edit_quiz_data': None,
}

for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# Initial load
if "quizzes_loaded" not in st.session_state:
    load_quizzes()
    st.session_state.quizzes_loaded = True

# ───────────────────────────────────────────────
# Admin helpers
# ───────────────────────────────────────────────

ADMIN_PASSWORD = "quizmaster2025"  # ← CHANGE THIS or move to secrets!

def is_admin():
    return st.session_state.get("admin_logged_in", False)

# ───────────────────────────────────────────────
# Category & Hierarchy helpers
# ───────────────────────────────────────────────

def get_all_departments():
    depts = set()
    for quiz in st.session_state.quizzes.values():
        dept = quiz.get("department") or quiz.get("category")
        if dept:
            depts.add(dept)
    return sorted(depts)


def get_all_levels():
    levels = set()
    for quiz in st.session_state.quizzes.values():
        if lvl := quiz.get("level"):
            levels.add(lvl)
    return sorted(levels) if levels else ["100 Level", "200 Level", "300 Level", "400 Level"]


def get_all_semesters():
    sems = set()
    for quiz in st.session_state.quizzes.values():
        if sem := quiz.get("semester"):
            sems.add(sem)
    return sorted(sems) if sems else ["First Semester", "Second Semester"]


def get_weeks_for(selected_levels, selected_semesters):
    weeks = set()
    for quiz in st.session_state.quizzes.values():
        if ((not selected_levels or quiz.get("level") in selected_levels) and
            (not selected_semesters or quiz.get("semester") in selected_semesters) and
            (wk := quiz.get("week"))):
            weeks.add(wk)
    return sorted(weeks)


def get_categories_for(selected_levels, selected_semesters, selected_weeks):
    cats = set()
    for quiz in st.session_state.quizzes.values():
        match = True
        if selected_levels and quiz.get("level") not in selected_levels:
            match = False
        if selected_semesters and quiz.get("semester") not in selected_semesters:
            match = False
        if selected_weeks and quiz.get("week") not in selected_weeks:
            match = False
        if match and (cat := quiz.get("quiz_category")):
            cats.add(cat)
    return sorted(cats)


def get_subcategories_for_depts(selected_depts):  # kept for backward compatibility if needed
    subs = set()
    for quiz in st.session_state.quizzes.values():
        dept = quiz.get("department") or quiz.get("category")
        sub = quiz.get("subcategory") or quiz.get("topic")
        if dept in selected_depts and sub:
            subs.add(sub)
    return sorted(subs)

# ───────────────────────────────────────────────
# Add new quiz (admin only)
# ───────────────────────────────────────────────

def submit_quiz_section():
    st.header("Add New Quiz (JSON)")
    tab1, tab2 = st.tabs(["Paste JSON", "Upload file"])
    all_depts = get_all_departments() or ["Uncategorized"]
    all_depts = sorted(set(all_depts + ["Uncategorized"]))

    with tab1:
        quiz_json = st.text_area("Quiz JSON", height=240, placeholder="Paste valid quiz JSON here...")
        quiz_title = st.text_input("Quiz title (optional)", key="new_quiz_title")

        department = st.selectbox(
            "Department / Category",
            options=all_depts + ["New department..."],
            key="new_quiz_dept_select"
        )
        new_dept = ""
        if department == "New department...":
            new_dept = st.text_input("Enter new department name", key="new_dept_input").strip()
        final_dept = new_dept or department

        subcategory = st.text_input("Sub-category / Topic (optional)", key="new_quiz_subcat").strip()

        # ── New hierarchy fields ───────────────────────
        level_options = [""] + get_all_levels()
        level = st.selectbox("Level", options=level_options, key="new_level")
        if level == "Other...":
            level = st.text_input("Custom level", key="new_custom_level").strip()

        semester = st.selectbox("Semester", options=["", "First Semester", "Second Semester"], key="new_semester")

        week = st.text_input("Week (e.g. Week 3, Midterm, Revision)", key="new_week").strip()

        quiz_category = st.text_input("Quiz Category (e.g. Quiz 1, Past Questions, Theory)", key="new_quiz_cat").strip()

        if st.button("Submit JSON", type="primary", key="submit_json"):
            if not quiz_json.strip():
                st.error("Please paste some JSON.")
                return
            try:
                data = json.loads(quiz_json)
                title = quiz_title.strip() or data.get("quiz_title") or f"Quiz_{len(st.session_state.quizzes)+1}"
                if final_dept and final_dept != "Uncategorized":
                    data["department"] = final_dept
                if subcategory:
                    data["subcategory"] = subcategory

                # Save new fields if provided
                if level:
                    data["level"] = level
                if semester:
                    data["semester"] = semester
                if week:
                    data["week"] = week
                if quiz_category:
                    data["quiz_category"] = quiz_category

                save_quiz(title, data)
            except json.JSONDecodeError:
                st.error("Invalid JSON format.")
            except Exception as e:
                st.error(f"Error: {e}")

    with tab2:
        uploaded = st.file_uploader("Upload .json file", type=["json"])
        if uploaded and st.button("Process uploaded file", key="submit_file"):
            try:
                data = json.load(uploaded)
                title = data.get("quiz_title", uploaded.name.replace(".json", ""))
                if not data.get("department"):
                    data["department"] = "Uncategorized"
                save_quiz(title, data)
            except Exception as e:
                st.error(f"Error: {e}")

# ───────────────────────────────────────────────
# Edit quiz form (admin only)
# ───────────────────────────────────────────────

def edit_quiz_form():
    if not st.session_state.get('edit_quiz_title'):
        return
    title = st.session_state.edit_quiz_title
    data = st.session_state.edit_quiz_data
    st.subheader(f"Editing Quiz: {title}")

    edited_title = st.text_input("Quiz Title", value=data.get("quiz_title", title), key="edit_title_input")

    all_depts = get_all_departments() or ["Uncategorized"]
    all_depts = sorted(set(all_depts + ["Uncategorized"]))
    current_dept = data.get("department") or data.get("category", "Uncategorized")
    dept_index = all_depts.index(current_dept) if current_dept in all_depts else 0

    department = st.selectbox(
        "Department / Category",
        options=all_depts + ["New department..."],
        index=dept_index,
        key="edit_dept_select"
    )
    new_dept = ""
    if department == "New department...":
        new_dept = st.text_input("New department name", key="edit_new_dept_input").strip()
    final_dept = new_dept or department

    current_subcat = data.get("subcategory", "")
    subcategory = st.text_input("Sub-category / Topic (optional)", value=current_subcat, key="edit_subcat_input")

    # ── Edit hierarchy fields ─────────────────────────
    current_level = data.get("level", "")
    level_options = [""] + get_all_levels()
    if current_level and current_level not in level_options:
        level_options.append(current_level)
    level = st.selectbox("Level", options=level_options, index=level_options.index(current_level) if current_level in level_options else 0, key="edit_level")

    current_sem = data.get("semester", "")
    semester = st.selectbox("Semester", options=["", "First Semester", "Second Semester"], index=["", "First Semester", "Second Semester"].index(current_sem) if current_sem in ["", "First Semester", "Second Semester"] else 0, key="edit_semester")

    week = st.text_input("Week", value=data.get("week", ""), key="edit_week")

    quiz_cat = st.text_input("Quiz Category", value=data.get("quiz_category", ""), key="edit_quiz_cat")

    current_json = json.dumps(data, indent=2, ensure_ascii=False)
    edited_json = st.text_area("Quiz JSON (edit carefully)", value=current_json, height=400, key="edit_json_area")

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("💾 Save Changes", type="primary"):
            try:
                new_data = json.loads(edited_json)
                new_data["quiz_title"] = edited_title.strip() or title
                if final_dept and final_dept != "Uncategorized":
                    new_data["department"] = final_dept
                else:
                    new_data.pop("department", None)
                if subcategory.strip():
                    new_data["subcategory"] = subcategory.strip()
                else:
                    new_data.pop("subcategory", None)

                # Update hierarchy fields
                if level:
                    new_data["level"] = level
                else:
                    new_data.pop("level", None)
                if semester:
                    new_data["semester"] = semester
                else:
                    new_data.pop("semester", None)
                if week.strip():
                    new_data["week"] = week.strip()
                else:
                    new_data.pop("week", None)
                if quiz_cat.strip():
                    new_data["quiz_category"] = quiz_cat.strip()
                else:
                    new_data.pop("quiz_category", None)

                save_quiz(edited_title.strip() or title, new_data)
                st.session_state.edit_quiz_title = None
                st.session_state.edit_quiz_data = None
                st.rerun()
            except json.JSONDecodeError:
                st.error("Invalid JSON format — please fix the syntax.")
            except Exception as e:
                st.error(f"Could not save changes: {e}")

    with col_cancel:
        if st.button("Cancel / Close editor"):
            st.session_state.edit_quiz_title = None
            st.session_state.edit_quiz_data = None
            st.rerun()

# ───────────────────────────────────────────────
# Take quiz section (unchanged)
# ───────────────────────────────────────────────

def take_quiz_section():
    quiz = st.session_state.quizzes[st.session_state.selected_quiz]
    title = quiz.get('quiz_title', st.session_state.selected_quiz)
    dept = quiz.get('department', quiz.get('category', 'Uncategorized'))
    subcat = quiz.get('subcategory', '')
    original_questions = quiz.get("questions", [])

    st.header(f"Quiz: {title}")
    st.caption(f"Department: **{dept}**" + (f" • Topic: **{subcat}**" if subcat else ""))

    if st.session_state.quiz_start_time is None and not st.session_state.show_answers:
        st.session_state.shuffled_questions = None
        st.session_state.option_shuffles = {}

    if st.session_state.shuffled_questions is None and original_questions:
        shuffled_idx = list(range(len(original_questions)))
        random.shuffle(shuffled_idx)
        st.session_state.shuffled_questions = [original_questions[i] for i in shuffled_idx]
        st.session_state.option_shuffles = {}
        for orig_i, q in enumerate(original_questions):
            opts = q.get("options", [])
            if not opts: continue
            opt_idx = list(range(len(opts)))
            random.shuffle(opt_idx)
            st.session_state.option_shuffles[orig_i] = opt_idx

    shuffled_questions = st.session_state.shuffled_questions or original_questions

    timer_placeholder = st.empty()

    if st.session_state.quiz_start_time is None and not st.session_state.show_answers:
        st.info("Optional: choose a time limit for this attempt")
        time_options = [
            "No timer", "5 minutes", "10 minutes", "15 minutes", "20 minutes",
            "25 minutes", "30 minutes", "40 minutes", "50 minutes", "60 minutes"
        ]
        selected_time = st.selectbox(
            "Time limit",
            options=time_options,
            index=0,
            key="time_limit_select"
        )
        if st.button("Start Quiz", type="primary"):
            if selected_time != "No timer":
                try:
                    minutes = int(selected_time.split()[0])
                    st.session_state.time_limit_minutes = minutes
                    st.session_state.quiz_start_time = datetime.now()
                except:
                    st.session_state.time_limit_minutes = None
                    st.session_state.quiz_start_time = datetime.now()
            else:
                st.session_state.time_limit_minutes = None
                st.session_state.quiz_start_time = datetime.now()
            st.rerun()

    timer_running = False
    if st.session_state.quiz_start_time is not None and not st.session_state.show_answers:
        elapsed = datetime.now() - st.session_state.quiz_start_time
        remaining_sec = 999_999_999
        if st.session_state.get('time_limit_minutes'):
            remaining_sec = max(0, int(st.session_state.time_limit_minutes * 60 - elapsed.total_seconds()))
        if remaining_sec <= 0 and st.session_state.get('time_limit_minutes'):
            st.session_state.timer_expired = True
            st.session_state.show_answers = True
            timer_placeholder.error("⏰ Time's up! Quiz auto-submitted.")
            st.rerun()
        else:
            if st.session_state.get('time_limit_minutes'):
                mins, secs = divmod(remaining_sec, 60)
                timer_placeholder.caption(f"⏳ **Time remaining: {mins:02d}:{secs:02d}**")
            else:
                timer_placeholder.caption("⏳ No time limit")
            timer_running = True

    for i, q in enumerate(shuffled_questions):
        st.subheader(f"Q{i+1}. {q.get('question', '—')}")
        orig_idx = original_questions.index(q)
        opts_orig = q.get("options", [])
        correct = q.get("correct")
        if not opts_orig or correct not in opts_orig:
            st.error(f"Q{i+1}: Invalid question data")
            continue

        shuffle_map = st.session_state.option_shuffles.get(orig_idx, list(range(len(opts_orig))))
        opts_shuffled = [opts_orig[j] for j in shuffle_map]

        key = f"ans_{i}"
        if not st.session_state.show_answers and not st.session_state.timer_expired:
            choice = st.radio("Your answer:", opts_shuffled,
                              index=st.session_state.user_answers.get(i, None),
                              key=key, horizontal=False)
            if choice is not None:
                st.session_state.user_answers[i] = opts_shuffled.index(choice)
        else:
            user_idx = st.session_state.user_answers.get(i, None)
            correct_shuf_idx = shuffle_map.index(opts_orig.index(correct))
            st.radio("Your selection:", opts_shuffled,
                     index=user_idx if user_idx is not None else 0,
                     key=f"rev_{key}", disabled=True, horizontal=True)
            if st.session_state.reveal_correct_answers:
                if user_idx is None:
                    st.warning("Skipped")
                    st.markdown(f"**Correct:** {correct}")
                elif user_idx == correct_shuf_idx:
                    st.success("Correct ✓")
                else:
                    st.error("Incorrect ✗")
                    st.markdown(f"**Correct:** {correct}")
                if expl := q.get("explanation", ""):
                    with st.expander("Explanation"):
                        st.write(expl)
        st.markdown("---")

    quiz_ended = st.session_state.show_answers or st.session_state.timer_expired

    if not quiz_ended:
        if st.button("Submit Quiz", type="primary"):
            correct_count = 0
            for i, q in enumerate(shuffled_questions):
                orig_i = original_questions.index(q)
                u_idx = st.session_state.user_answers.get(i)
                if u_idx is None: continue
                map_ = st.session_state.option_shuffles.get(orig_i, [])
                orig_choice_idx = map_[u_idx]
                if q["options"][orig_choice_idx] == q["correct"]:
                    correct_count += 1
            st.session_state.score = (correct_count, len(shuffled_questions))
            st.session_state.show_answers = True
            st.rerun()

    else:
        if st.session_state.score:
            c, t = st.session_state.score
            pct = c / t * 100 if t > 0 else 0
            st.success(f"**Score: {c}/{t}** ({pct:.0f}%)")

        if not st.session_state.reveal_correct_answers:
            if st.button("Show correct answers & explanations"):
                st.session_state.reveal_correct_answers = True
                st.rerun()
        else:
            if st.button("Hide correct answers"):
                st.session_state.reveal_correct_answers = False
                st.rerun()

    if quiz_ended:
        if st.button("Restart this quiz"):
            for k in ['user_answers','show_answers','score','quiz_start_time',
                      'time_limit_minutes','timer_expired','reveal_correct_answers',
                      'shuffled_questions','option_shuffles']:
                if k in st.session_state:
                    v = st.session_state[k]
                    if isinstance(v, dict):
                        v.clear()
                    else:
                        st.session_state[k] = None
            st.rerun()

    if timer_running:
        time.sleep(1)
        st.rerun()

# ───────────────────────────────────────────────
# Main Layout
# ───────────────────────────────────────────────

st.title("NextGen Dev")

with st.sidebar:
    if not is_admin():
        with st.expander("Admin Zone"):
            pwd = st.text_input("Admin password", type="password")
            if st.button("Login as Admin"):
                if pwd.strip() == ADMIN_PASSWORD:
                    st.session_state.admin_logged_in = True
                    st.rerun()
                else:
                    st.error("Wrong password")
    else:
        st.success("Admin mode active")
        if st.button("Logout"):
            st.session_state.admin_logged_in = False
            st.rerun()

    st.divider()
    st.header("Find Quiz")

    all_depts = get_all_departments() or ["Uncategorized"]
    selected_depts = st.multiselect(
        "Department",
        options=sorted(all_depts),
        default=[],
        placeholder="Select department(s)",
        key="dept_multi"
    )

    selected_levels = []
    if selected_depts:
        selected_levels = st.multiselect(
            "Level",
            options=get_all_levels(),
            default=[],
            placeholder="Select level(s)",
            key="level_multi"
        )

    selected_semesters = []
    if selected_depts and selected_levels:
        selected_semesters = st.multiselect(
            "Semester",
            options=get_all_semesters(),
            default=[],
            placeholder="Select semester(s)",
            key="sem_multi"
        )

    selected_weeks = []
    if selected_depts and selected_levels and selected_semesters:
        selected_weeks = st.multiselect(
            "Week",
            options=get_weeks_for(selected_levels, selected_semesters),
            default=[],
            placeholder="Select week(s)",
            key="week_multi"
        )

    selected_categories = []
    if selected_depts and selected_levels and selected_semesters and selected_weeks:
        selected_categories = st.multiselect(
            "Quiz Category / Type",
            options=get_categories_for(selected_levels, selected_semesters, selected_weeks),
            default=[],
            placeholder="Select category",
            key="cat_multi"
        )

    # Store selections
    st.session_state.selected_departments = selected_depts
    st.session_state.selected_levels = selected_levels
    st.session_state.selected_semesters = selected_semesters
    st.session_state.selected_weeks = selected_weeks
    st.session_state.selected_categories = selected_categories

    st.header("Available Quizzes")

    if not selected_depts:
        st.info("Select at least one department to see quizzes.")
    else:
        filtered = {}
        for title, quiz in st.session_state.quizzes.items():
            ok = True
            if selected_depts and (quiz.get("department") or quiz.get("category")) not in selected_depts:
                ok = False
            if selected_levels and quiz.get("level") not in selected_levels:
                ok = False
            if selected_semesters and quiz.get("semester") not in selected_semesters:
                ok = False
            if selected_weeks and quiz.get("week") not in selected_weeks:
                ok = False
            if selected_categories and quiz.get("quiz_category") not in selected_categories:
                ok = False

            if ok:
                parts = []
                if quiz.get("level"): parts.append(quiz["level"])
                if quiz.get("semester"): parts.append(quiz["semester"])
                if quiz.get("week"): parts.append(quiz["week"])
                if quiz.get("quiz_category"): parts.append(quiz["quiz_category"])
                label = title
                if parts:
                    label += "  •  " + " → ".join(parts)
                filtered[label] = title

        if not filtered:
            st.info("No quizzes match the selected filters.")
        else:
            st.caption(f"Found {len(filtered)} quiz{'zes' if len(filtered)!=1 else ''}")
            for label, real_title in sorted(filtered.items()):
                cols = st.columns([4, 1, 1])
                with cols[0]:
                    active = real_title == st.session_state.selected_quiz
                    if st.button(label, key=f"q_{real_title}",
                                 type="primary" if active else "secondary",
                                 use_container_width=True):
                        if not active:
                            st.session_state.selected_quiz = real_title
                            for k in ['user_answers','show_answers','score','quiz_start_time',
                                      'time_limit_minutes','timer_expired','reveal_correct_answers',
                                      'shuffled_questions','option_shuffles']:
                                if k in st.session_state:
                                    v = st.session_state[k]
                                    if isinstance(v, dict):
                                        v.clear()
                                    else:
                                        st.session_state[k] = None
                            st.rerun()
                with cols[1]:
                    if is_admin():
                        if st.button("✏️", key=f"e_{real_title}", help="Edit quiz"):
                            st.session_state.edit_quiz_title = real_title
                            st.session_state.edit_quiz_data = st.session_state.quizzes[real_title].copy()
                            st.rerun()
                with cols[2]:
                    if is_admin():
                        if st.button("🗑", key=f"d_{real_title}", help="Delete quiz"):
                            delete_quiz(real_title)
                            st.rerun()

    st.divider()
    if is_admin():
        submit_quiz_section()
    else:
        st.caption("Quiz creation restricted to admin.")

# ── Main content ────────────────────────────────────────

if not st.session_state.selected_departments:
    st.info("Select at least one department from the sidebar to view available quizzes.")
elif st.session_state.selected_quiz:
    take_quiz_section()
else:
    st.info("Choose a quiz from the list in the sidebar.")

# ── Edit form (shown in main area when active) ───────────────

if is_admin() and st.session_state.get('edit_quiz_title'):
    edit_quiz_form()