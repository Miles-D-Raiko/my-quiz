import streamlit as st
import json
from datetime import datetime
import time
import random
import pymongo
from pymongo.errors import DuplicateKeyError

# ───────────────────────────────────────────────
# MongoDB Helpers
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
        client.admin.command('ping')
        return client
    except Exception as e:
        st.error(f"Failed to connect to MongoDB:\n{str(e)}\n\n"
                 "Common fixes:\n"
                 "• Check username/password\n"
                 "• Make sure your IP is allowed in Atlas Network Access\n"
                 "• Verify the connection string includes ?retryWrites=true&w=majority")
        st.stop()


@st.cache_resource(ttl=1800)
def get_quizzes_collection():
    client = get_mongo_client()
    db_name = st.secrets.mongo.get("db_name", "NextgenDev")
    coll_name = st.secrets.mongo.get("collection_name", "quizzes")
   
    db = client[db_name]
    coll = db[coll_name]
    try:
        coll.create_index("quiz_title", unique=True, background=True)
    except:
        pass
    return coll


def load_quizzes():
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
    coll = get_quizzes_collection()
    data = data.copy()
    data["quiz_title"] = title
   
    try:
        coll.replace_one(
            {"quiz_title": title},
            data,
            upsert=True
        )
        st.success(f"Quiz **{title}** saved/updated.")
        load_quizzes()
        # Force index rebuild after save/delete
        if "quiz_index" in st.session_state:
            del st.session_state.quiz_index
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
            # Force index rebuild
            if "quiz_index" in st.session_state:
                del st.session_state.quiz_index
            st.rerun()
        else:
            st.warning(f"Quiz '{title}' not found in database.")
    except Exception as e:
        st.error(f"Delete failed: {e}")


# ───────────────────────────────────────────────
# Improved: Single cached index for fast filtering
# ───────────────────────────────────────────────
@st.cache_data(ttl=600, show_spinner=False)
def build_quiz_index():
    index = {
        "departments": set(),
        "levels": set(),
        "semesters": set(),
        "courses_by": {},          # (dept, level, sem) → set(courses)
        "weeks_by": {},            # (level, sem, course) → set(weeks)
        "categories_by": {},       # (level, sem, course, week) → set(categories)
    }

    for quiz in st.session_state.quizzes.values():
        dept   = quiz.get("department") or quiz.get("category", "Uncategorized")
        level  = quiz.get("level")
        sem    = quiz.get("semester")
        course = quiz.get("course")
        week   = quiz.get("week")
        cat    = quiz.get("quiz_category")

        index["departments"].add(dept)
        if level:  index["levels"].add(level)
        if sem:    index["semesters"].add(sem)

        # Only store deeper keys if parent exists
        if dept and level and sem and course:
            key = (dept, level, sem)
            index["courses_by"].setdefault(key, set()).add(course)

        if level and sem and course and week:
            key = (level, sem, course)
            index["weeks_by"].setdefault(key, set()).add(week)

        if level and sem and course and week and cat:
            key = (level, sem, course, week)
            index["categories_by"].setdefault(key, set()).add(cat)

    # Prepare sorted lists for UI
    index["departments"] = sorted(index["departments"])
    index["levels"]      = sorted(index["levels"]) or ["100 Level", "200 Level", "300 Level", "400 Level"]
    index["semesters"]   = sorted(index["semesters"]) or ["First Semester", "Second Semester"]

    for k in ["courses_by", "weeks_by", "categories_by"]:
        for subkey in index[k]:
            index[k][subkey] = sorted(f for f in index[k][subkey] if f)

    return index


def get_all_departments():
    idx = st.session_state.get("quiz_index") or build_quiz_index()
    return idx["departments"]


def get_all_levels():
    idx = st.session_state.get("quiz_index") or build_quiz_index()
    return idx["levels"]


def get_all_semesters():
    idx = st.session_state.get("quiz_index") or build_quiz_index()
    return idx["semesters"]


def get_courses_for(selected_depts, selected_levels, selected_semesters):
    if not (selected_depts and selected_levels and selected_semesters):
        return []
    idx = st.session_state.get("quiz_index") or build_quiz_index()
    courses = set()
    for d in selected_depts:
        for l in selected_levels:
            for s in selected_semesters:
                key = (d, l, s)
                courses.update(idx["courses_by"].get(key, set()))
    return sorted(c for c in courses if c)


def get_weeks_for(selected_levels, selected_semesters, selected_courses):
    if not (selected_levels and selected_semesters and selected_courses):
        return []
    idx = st.session_state.get("quiz_index") or build_quiz_index()
    weeks = set()
    for l in selected_levels:
        for s in selected_semesters:
            for c in selected_courses:
                key = (l, s, c)
                weeks.update(idx["weeks_by"].get(key, set()))
    return sorted(w for w in weeks if w)


def get_categories_for(selected_levels, selected_semesters, selected_courses, selected_weeks):
    if not (selected_levels and selected_semesters and selected_courses and selected_weeks):
        return []
    idx = st.session_state.get("quiz_index") or build_quiz_index()
    cats = set()
    for l in selected_levels:
        for s in selected_semesters:
            for c in selected_courses:
                for w in selected_weeks:
                    key = (l, s, c, w)
                    cats.update(idx["categories_by"].get(key, set()))
    return sorted(c for c in cats if c)


# ───────────────────────────────────────────────
# Scoring helper (unchanged)
# ───────────────────────────────────────────────
def _calculate_and_store_score(shuffled_questions, original_questions):
    correct_count = 0
    for i, q in enumerate(shuffled_questions):
        orig_i = original_questions.index(q)
        u_idx = st.session_state.user_answers.get(i)
        if u_idx is None:
            continue
        map_ = st.session_state.option_shuffles.get(orig_i, [])
        orig_choice_idx = map_[u_idx]
        if q["options"][orig_choice_idx] == q["correct"]:
            correct_count += 1
    st.session_state.score = (correct_count, len(shuffled_questions))


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
    'selected_courses': [],
    'selected_weeks': [],
    'selected_categories': [],
    'admin_logged_in': False,
    'shuffled_questions': None,
    'option_shuffles': {},
    'edit_quiz_title': None,
    'edit_quiz_data': None,
    'edit_working_copy': None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

if "quizzes_loaded" not in st.session_state:
    load_quizzes()
    st.session_state.quizzes_loaded = True


# Force index on first load / after data change
if "quiz_index" not in st.session_state:
    st.session_state.quiz_index = build_quiz_index()


# ───────────────────────────────────────────────
# Admin check
# ───────────────────────────────────────────────
def is_admin():
    return st.session_state.get("admin_logged_in", False)


# ───────────────────────────────────────────────
# Add new quiz (unchanged)
# ───────────────────────────────────────────────
def submit_quiz_section():
    st.header("Add New Quiz (JSON)")
    tab1, tab2 = st.tabs(["Paste JSON", "Upload file"])
    all_depts = sorted(set(get_all_departments()) | {"Uncategorized"})

    with tab1:
        quiz_json = st.text_area("Quiz JSON", height=240, placeholder="Paste valid quiz JSON here...", key="add_quiz_json")
        quiz_title = st.text_input("Quiz title (optional)", key="add_quiz_title")

        department = st.selectbox("Department / Category", options=all_depts + ["New department..."], key="add_dept_select")
        new_dept = ""
        if department == "New department...":
            new_dept = st.text_input("Enter new department name", key="add_new_dept_input").strip()
        final_dept = new_dept or department

        subcategory = st.text_input("Sub-category / Topic (optional)", key="add_subcat").strip()

        level = st.selectbox("Level", [""] + get_all_levels() + ["Other..."], key="add_level")
        if level == "Other...":
            level = st.text_input("Custom level", key="add_custom_level").strip()

        semester = st.selectbox("Semester", ["", "First Semester", "Second Semester", "Other..."], key="add_semester")
        if semester == "Other...":
            semester = st.text_input("Custom semester", key="add_custom_semester").strip()

        course = st.text_input("Course (e.g. CSC 101, MAT 111)", key="add_course").strip()

        week = st.text_input("Week (e.g. Week 3, Midterm, Revision)", key="add_week").strip()

        quiz_category = st.text_input("Quiz Category (e.g. Quiz 1, Past Questions, Theory)", key="add_quiz_cat").strip()

        if st.button("Submit JSON", type="primary", key="add_submit_json"):
            if not quiz_json.strip():
                st.error("Please paste some JSON.")
                return
            try:
                data = json.loads(quiz_json)
                title = quiz_title.strip() or data.get("quiz_title") or f"Quiz_{len(st.session_state.quizzes)+1}"
                if final_dept and final_dept != "Uncategorized":
                    data["department"] = final_dept
                if subcategory: data["subcategory"] = subcategory
                if level: data["level"] = level
                if semester: data["semester"] = semester
                if course: data["course"] = course
                if week: data["week"] = week
                if quiz_category: data["quiz_category"] = quiz_category
                save_quiz(title, data)
            except json.JSONDecodeError:
                st.error("Invalid JSON format.")
            except Exception as e:
                st.error(f"Error: {e}")

    with tab2:
        uploaded = st.file_uploader("Upload .json file", type=["json"], key="add_upload_file")
        if uploaded and st.button("Process uploaded file", key="add_process_file"):
            try:
                data = json.load(uploaded)
                title = data.get("quiz_title", uploaded.name.replace(".json", ""))
                if not data.get("department"):
                    data["department"] = "Uncategorized"
                save_quiz(title, data)
            except Exception as e:
                st.error(f"Error: {e}")


# ───────────────────────────────────────────────
# Organize quizzes section (unchanged – but now uses fast getters)
# ───────────────────────────────────────────────
def organize_quizzes_section():
    st.subheader("Organize / Move Existing Quizzes")
    if not st.session_state.quizzes:
        st.info("No quizzes available yet.")
        return

    search_term = st.text_input("Filter by title", "", key="org_search").strip().lower()

    for title, quiz in sorted(st.session_state.quizzes.items()):
        if search_term and search_term not in title.lower():
            continue

        with st.expander(f"📄 {title}", expanded=False):
            st.caption("Current assignment:")
            st.markdown(f"""
            • **Level:** {quiz.get('level', '—')}  
            • **Semester:** {quiz.get('semester', '—')}  
            • **Course:** {quiz.get('course', '—')}  
            • **Week:** {quiz.get('week', '—')}  
            • **Category:** {quiz.get('quiz_category', '—')}
            """)

            st.divider()

            lvl_opts = [""] + get_all_levels()
            new_level = st.selectbox(
                "Level",
                options=lvl_opts + ["Other..."],
                index=lvl_opts.index(quiz.get("level", "")) if quiz.get("level") in lvl_opts else 0,
                key=f"org_level_{title}"
            )
            if new_level == "Other...":
                new_level = st.text_input("Custom level", key=f"org_lvl_custom_{title}").strip() or quiz.get("level", "")

            sem_opts = ["", "First Semester", "Second Semester"]
            new_sem = st.selectbox(
                "Semester",
                options=sem_opts + ["Other..."],
                index=sem_opts.index(quiz.get("semester", "")) if quiz.get("semester") in sem_opts else 0,
                key=f"org_sem_{title}"
            )
            if new_sem == "Other...":
                new_sem = st.text_input("Custom semester", key=f"org_sem_custom_{title}").strip() or quiz.get("semester", "")

            new_course = st.text_input("Course", value=quiz.get("course", ""), key=f"org_course_{title}").strip()
            new_week   = st.text_input("Week",   value=quiz.get("week", ""),   key=f"org_week_{title}").strip()
            new_cat    = st.text_input("Quiz Category", value=quiz.get("quiz_category", ""), key=f"org_cat_{title}").strip()

            if st.button("💾 Save assignment", type="primary", key=f"save_org_{title}"):
                updated = quiz.copy()
                changed = False
                if new_level and new_level != quiz.get("level"):
                    updated["level"] = new_level
                    changed = True
                if new_sem and new_sem != quiz.get("semester"):
                    updated["semester"] = new_sem
                    changed = True
                if new_course and new_course != quiz.get("course"):
                    updated["course"] = new_course
                    changed = True
                if new_week and new_week != quiz.get("week"):
                    updated["week"] = new_week
                    changed = True
                if new_cat and new_cat != quiz.get("quiz_category"):
                    updated["quiz_category"] = new_cat
                    changed = True

                if changed:
                    save_quiz(title, updated)
                    st.success("Saved!")
                    st.rerun()
                else:
                    st.info("No changes detected.")


# ───────────────────────────────────────────────
# Take quiz section (minor tweak: timer only reruns when no edit mode)
# ───────────────────────────────────────────────
def take_quiz_section():
    quiz = st.session_state.quizzes[st.session_state.selected_quiz]
    title = quiz.get('quiz_title', st.session_state.selected_quiz)
    dept = quiz.get('department', quiz.get('category', 'Uncategorized'))
    subcat = quiz.get('subcategory', '')

    original_questions = quiz.get("questions", [])

    st.header(f"Quiz: {title}")
    st.caption(f"Department: **{dept}**" + (f" • Topic: **{subcat}**" if subcat else ""))

    timer_active = False
    remaining_sec = None
    mins, secs = 0, 0

    if st.session_state.quiz_start_time and not st.session_state.show_answers:
        elapsed = datetime.now() - st.session_state.quiz_start_time
        if st.session_state.get('time_limit_minutes'):
            remaining_sec = max(0, int(st.session_state.time_limit_minutes * 60 - elapsed.total_seconds()))
            mins, secs = divmod(remaining_sec, 60)
            if remaining_sec <= 0:
                st.session_state.timer_expired = True
                st.session_state.show_answers = True
                st.rerun()
        timer_active = True

    if timer_active:
        if remaining_sec is not None:
            if remaining_sec <= 60:
                st.error(f"⏳ **{mins:02d}:{secs:02d} remaining** — Time is almost up!")
            elif remaining_sec <= 300:
                st.warning(f"⏳ **{mins:02d}:{secs:02d}** remaining")
            else:
                st.info(f"⏳ Time remaining: **{mins:02d}:{secs:02d}**")
        else:
            st.info("⏳ No time limit — take your time")

    if st.session_state.quiz_start_time is None and not st.session_state.show_answers:
        st.markdown("---")
        st.info("Optional: select a time limit then click **Start Quiz** below.")

        time_options = [
            "No timer", "5 minutes", "10 minutes", "15 minutes", "20 minutes",
            "25 minutes", "30 minutes", "40 minutes", "50 minutes", "60 minutes"
        ]
        selected_time = st.selectbox(
            "Time limit for this attempt",
            options=time_options,
            index=0,
            key="time_limit_select_unique"
        )

        if st.button("Start Quiz", type="primary", use_container_width=True):
            if selected_time != "No timer":
                try:
                    st.session_state.time_limit_minutes = int(selected_time.split()[0])
                except:
                    st.session_state.time_limit_minutes = None
            else:
                st.session_state.time_limit_minutes = None
            st.session_state.quiz_start_time = datetime.now()
            st.rerun()

        st.markdown("---")
        return

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

        key = f"ans_{i}_{title}"

        if not st.session_state.show_answers and not st.session_state.timer_expired:
            choice = st.radio(
                "Your answer:",
                opts_shuffled,
                index=st.session_state.user_answers.get(i, None),
                key=key,
                horizontal=False
            )
            if choice is not None:
                st.session_state.user_answers[i] = opts_shuffled.index(choice)
        else:
            user_idx = st.session_state.user_answers.get(i, None)
            correct_shuf_idx = shuffle_map.index(opts_orig.index(correct))

            st.radio(
                "Your selection:",
                opts_shuffled,
                index=user_idx if user_idx is not None else 0,
                key=f"rev_{key}",
                disabled=True,
                horizontal=True
            )

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
        st.markdown("---")
        col_reminder, col_submit = st.columns([1, 2])

        with col_reminder:
            if timer_active and remaining_sec is not None:
                if remaining_sec <= 300:
                    st.markdown(f"**⏳ {mins:02d}:{secs:02d} left**", unsafe_allow_html=True)
                else:
                    st.caption(f"Time left: **{mins:02d}:{secs:02d}**")
            else:
                st.caption("No time limit")

        with col_submit:
            if st.button("Submit Quiz", type="primary", use_container_width=True):
                _calculate_and_store_score(shuffled_questions, original_questions)
                st.session_state.show_answers = True
                st.rerun()

    else:
        if st.session_state.timer_expired and st.session_state.score is None:
            with st.spinner("Time's up! Calculating your score..."):
                time.sleep(0.8)
                _calculate_and_store_score(shuffled_questions, original_questions)
            st.rerun()

        if st.session_state.score:
            c, t = st.session_state.score
            pct = c / t * 100 if t > 0 else 0

            if st.session_state.timer_expired and not st.session_state.get('_time_up_message_shown', False):
                st.error("⏰ **Time's up!** Quiz was automatically submitted.")
                st.session_state['_time_up_message_shown'] = True

            st.success(f"**Score: {c}/{t}** ({pct:.0f}%)")

        if not st.session_state.reveal_correct_answers:
            if st.button("Show correct answers & explanations"):
                st.session_state.reveal_correct_answers = True
                st.rerun()
        else:
            if st.button("Hide correct answers"):
                st.session_state.reveal_correct_answers = False
                st.rerun()

        if st.button("Restart this quiz"):
            keys_to_reset = [
                'user_answers', 'show_answers', 'score',
                'quiz_start_time', 'time_limit_minutes',
                'timer_expired', 'reveal_correct_answers',
                'shuffled_questions', 'option_shuffles',
                '_time_up_message_shown'
            ]
            for k in keys_to_reset:
                if k in st.session_state:
                    v = st.session_state[k]
                    if isinstance(v, dict):
                        v.clear()
                    else:
                        st.session_state[k] = None
            st.rerun()

    # Timer auto-refresh — but skip if editing or no timer
    if timer_active and not quiz_ended and not st.session_state.get('edit_quiz_title') and remaining_sec is not None:
        time.sleep(1)
        st.rerun()


# ───────────────────────────────────────────────
# Main Layout
# ───────────────────────────────────────────────
st.title("NextGen Dev")

with st.sidebar:
    if not is_admin():
        with st.expander("Admin Zone"):
            pwd = st.text_input("Admin password", type="password", key="admin_pwd_input")
            if st.button("Login as Admin"):
                try:
                    correct_pwd = st.secrets["admin"]["password"]
                except (KeyError, AttributeError):
                    st.error("Admin password not configured in secrets.\n\n"
                             "Add to secrets.toml or Streamlit Cloud secrets:\n"
                             "[admin]\npassword = \"your-strong-password\"")
                    st.stop()

                if pwd.strip() == correct_pwd:
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
        default=st.session_state.selected_departments,
        placeholder="Select department(s)",
        key="filter_dept"
    )

    selected_levels = st.multiselect(
        "Level",
        options=get_all_levels(),
        default=st.session_state.selected_levels,
        placeholder="Select level(s)",
        key="filter_level",
        disabled=not selected_depts
    ) if selected_depts else []

    selected_semesters = st.multiselect(
        "Semester",
        options=get_all_semesters(),
        default=st.session_state.selected_semesters,
        placeholder="Select semester(s)",
        key="filter_semester",
        disabled=not (selected_depts and selected_levels)
    ) if selected_depts and selected_levels else []

    selected_courses = st.multiselect(
        "Course",
        options=get_courses_for(selected_depts, selected_levels, selected_semesters),
        default=st.session_state.selected_courses,
        placeholder="Select course(s)",
        key="filter_course",
        disabled=not (selected_depts and selected_levels and selected_semesters)
    ) if selected_depts and selected_levels and selected_semesters else []

    selected_weeks = st.multiselect(
        "Week",
        options=get_weeks_for(selected_levels, selected_semesters, selected_courses),
        default=st.session_state.selected_weeks,
        placeholder="Select week(s)",
        key="filter_week",
        disabled=not (selected_depts and selected_levels and selected_semesters and selected_courses)
    ) if selected_depts and selected_levels and selected_semesters and selected_courses else []

    selected_categories = st.multiselect(
        "Quiz Category / Type",
        options=get_categories_for(selected_levels, selected_semesters, selected_courses, selected_weeks),
        default=st.session_state.selected_categories,
        placeholder="Select category",
        key="filter_category",
        disabled=not (selected_depts and selected_levels and selected_semesters and selected_courses and selected_weeks)
    ) if selected_depts and selected_levels and selected_semesters and selected_courses and selected_weeks else []

    # Sync back to session state
    st.session_state.update({
        'selected_departments': selected_depts,
        'selected_levels': selected_levels,
        'selected_semesters': selected_semesters,
        'selected_courses': selected_courses,
        'selected_weeks': selected_weeks,
        'selected_categories': selected_categories,
    })

    st.header("Available Quizzes")

    if not selected_depts:
        st.info("Select at least one department to begin.")
    elif not selected_levels:
        st.info("Select level(s).")
    elif not selected_semesters:
        st.info("Select semester(s).")
    elif not selected_courses:
        st.info("Select course(s) to see available quizzes.")
    else:
        filtered = {}
        for title, quiz in st.session_state.quizzes.items():
            ok = True
            dept = quiz.get("department") or quiz.get("category", "Uncategorized")
            if selected_depts and dept not in selected_depts: ok = False
            if selected_levels and quiz.get("level") not in selected_levels: ok = False
            if selected_semesters and quiz.get("semester") not in selected_semesters: ok = False
            if selected_courses and quiz.get("course") not in selected_courses: ok = False
            if selected_weeks and quiz.get("week") not in selected_weeks: ok = False
            if selected_categories and quiz.get("quiz_category") not in selected_categories: ok = False

            if ok:
                parts = [quiz.get(k) for k in ["level", "semester", "course", "week", "quiz_category"] if quiz.get(k)]
                label = title
                if parts:
                    label += " • " + " → ".join(parts)
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
                            st.session_state.edit_working_copy = None
                            st.rerun()
                with cols[2]:
                    if is_admin():
                        if st.button("🗑", key=f"d_{real_title}", help="Delete quiz"):
                            delete_quiz(real_title)
                            st.rerun()

    st.divider()
    if is_admin():
        with st.expander("🗂️ Organize & Move Quizzes", expanded=False):
            organize_quizzes_section()

        with st.expander("➕ Add New Quiz", expanded=True):
            submit_quiz_section()
    else:
        st.caption("Quiz creation & organization restricted to admin.")


# ── Main content ─────────────────────────────────────────────────────────────
if not st.session_state.selected_departments:
    st.info("Select at least one department from the sidebar to view available quizzes.")
elif st.session_state.selected_quiz:
    take_quiz_section()
else:
    st.info("Choose a quiz from the list in the sidebar.")


# ── Live Edit Section (unchanged from previous version) ──────────────────────
if is_admin() and st.session_state.get('edit_quiz_title'):
    orig_title = st.session_state.edit_quiz_title

    if st.session_state.edit_working_copy is None:
        st.session_state.edit_working_copy = st.session_state.edit_quiz_data.copy()

    data = st.session_state.edit_working_copy

    st.markdown("---")
    st.subheader(f"Editing Quiz: {orig_title}")
    st.caption("Changes are live in memory — click **Save Changes** when finished (title change = rename)")

    edited_title      = st.session_state.get("edit_title_live",      data.get("quiz_title", orig_title))
    edited_dept       = st.session_state.get("edit_dept_live",       data.get("department", "Uncategorized"))
    edited_new_dept   = st.session_state.get("edit_new_dept_live",   "")
    edited_subcat     = st.session_state.get("edit_subcat_live",     data.get("subcategory", ""))
    edited_level      = st.session_state.get("edit_level_live",      data.get("level", ""))
    edited_level_cust = st.session_state.get("edit_level_cust_live", "")
    edited_sem        = st.session_state.get("edit_sem_live",        data.get("semester", ""))
    edited_sem_cust   = st.session_state.get("edit_sem_cust_live",   "")
    edited_course     = st.session_state.get("edit_course_live",     data.get("course", ""))
    edited_week       = st.session_state.get("edit_week_live",       data.get("week", ""))
    edited_cat        = st.session_state.get("edit_cat_live",        data.get("quiz_category", ""))

    st.text_input("Quiz Title", value=edited_title, key="edit_title_live")

    all_depts = sorted(set(get_all_departments()) | {"Uncategorized"})
    dept_index = all_depts.index(edited_dept) if edited_dept in all_depts else 0

    st.selectbox(
        "Department / Category",
        options=all_depts + ["New department..."],
        index=dept_index,
        key="edit_dept_live"
    )

    if edited_dept == "New department...":
        st.text_input("New department name", value=edited_new_dept, key="edit_new_dept_live")

    st.text_input("Sub-category / Topic (optional)", value=edited_subcat, key="edit_subcat_live")

    level_options = [""] + get_all_levels()
    if edited_level and edited_level not in level_options:
        level_options.append(edited_level)

    st.selectbox(
        "Level",
        options=level_options + ["Other..."],
        index=level_options.index(edited_level) if edited_level in level_options else 0,
        key="edit_level_live"
    )
    if edited_level == "Other...":
        st.text_input("Custom level", value=edited_level_cust, key="edit_level_cust_live")

    sem_options = ["", "First Semester", "Second Semester"]
    sem_index = sem_options.index(edited_sem) if edited_sem in sem_options else 0
    st.selectbox("Semester", options=sem_options + ["Other..."], index=sem_index, key="edit_sem_live")
    if edited_sem == "Other...":
        st.text_input("Custom semester", value=edited_sem_cust, key="edit_sem_cust_live")

    st.text_input("Course (e.g. CSC 101)", value=edited_course, key="edit_course_live")
    st.text_input("Week (e.g. Week 3, Midterm)", value=edited_week, key="edit_week_live")
    st.text_input("Quiz Category (e.g. Quiz 1, Past Questions)", value=edited_cat, key="edit_cat_live")

    final_dept = edited_new_dept.strip() if edited_dept == "New department..." else edited_dept

    data["quiz_title"]    = edited_title.strip() or orig_title
    if final_dept and final_dept != "Uncategorized":
        data["department"] = final_dept
    else:
        data.pop("department", None)

    data["subcategory"]   = edited_subcat.strip() or None
    data["level"]         = (edited_level_cust or edited_level).strip() or None
    data["semester"]      = (edited_sem_cust or edited_sem).strip() or None
    data["course"]        = edited_course.strip() or None
    data["week"]          = edited_week.strip() or None
    data["quiz_category"] = edited_cat.strip() or None

    for k in list(data):
        if data[k] in (None, "", "Uncategorized"):
            data.pop(k, None)

    st.markdown("---")
    st.caption("Advanced: override / extend everything (applied only on save)")
    current_json = json.dumps(data, indent=2, ensure_ascii=False)
    edited_json_area = st.text_area(
        "Full Quiz JSON override",
        value=current_json,
        height=280,
        key="edit_json_live"
    )

    col_save, col_cancel, col_reset = st.columns([2, 2, 1])

    with col_save:
        if st.button("💾 **Save Changes**", type="primary", use_container_width=True):
            try:
                final_data = data.copy()

                if edited_json_area.strip() and edited_json_area.strip() != current_json.strip():
                    try:
                        parsed = json.loads(edited_json_area)
                        final_data.update(parsed)
                        if st.session_state.get("edit_title_live"):
                            final_data["quiz_title"] = st.session_state.edit_title_live
                    except json.JSONDecodeError:
                        st.error("Invalid JSON — saving field changes only.")

                new_title = final_data.get("quiz_title", orig_title).strip()

                if new_title != orig_title:
                    if new_title in st.session_state.quizzes:
                        st.error(f"Cannot rename — quiz titled **{new_title}** already exists.")
                        st.stop()

                save_quiz(new_title, final_data)

                st.session_state.quizzes[new_title] = final_data.copy()
                if new_title != orig_title:
                    st.session_state.quizzes.pop(orig_title, None)
                    if st.session_state.selected_quiz == orig_title:
                        st.session_state.selected_quiz = new_title

                for k in ['edit_quiz_title', 'edit_quiz_data', 'edit_working_copy']:
                    st.session_state.pop(k, None)

                # Rebuild index after save
                st.session_state.quiz_index = build_quiz_index()

                st.success(f"Quiz **{new_title}** saved successfully!")
                st.rerun()

            except Exception as e:
                st.error(f"Save failed: {str(e)}")

    with col_cancel:
        if st.button("Cancel / Close", use_container_width=True):
            for k in ['edit_quiz_title', 'edit_quiz_data', 'edit_working_copy']:
                st.session_state.pop(k, None)
            st.rerun()

    with col_reset:
        if st.button("Reset", help="Revert all changes"):
            st.session_state.edit_working_copy = st.session_state.edit_quiz_data.copy()
            st.rerun()

    with st.expander("Current in-memory preview", expanded=False):
        st.json(data)