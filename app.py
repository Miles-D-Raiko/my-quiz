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
        coll.replace_one({"quiz_title": title}, data, upsert=True)
        st.success(f"Quiz **{title}** saved/updated.")
        load_quizzes()
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
            st.warning(f"Quiz '{title}' not found.")
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
    'selected_courses': [],          # ← added
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


if "quizzes_loaded" not in st.session_state:
    load_quizzes()
    st.session_state.quizzes_loaded = True


# ───────────────────────────────────────────────
# Admin helpers
# ───────────────────────────────────────────────
ADMIN_PASSWORD = "quizmaster2025"
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


def get_courses_for(selected_depts, selected_levels, selected_semesters):
    courses = set()
    for quiz in st.session_state.quizzes.values():
        dept = quiz.get("department") or quiz.get("category")
        if ((not selected_depts or dept in selected_depts) and
            (not selected_levels or quiz.get("level") in selected_levels) and
            (not selected_semesters or quiz.get("semester") in selected_semesters) and
            (course := quiz.get("course"))):
            courses.add(course)
    return sorted(courses)


def get_weeks_for(selected_levels, selected_semesters, selected_courses):
    weeks = set()
    for quiz in st.session_state.quizzes.values():
        if ((not selected_levels or quiz.get("level") in selected_levels) and
            (not selected_semesters or quiz.get("semester") in selected_semesters) and
            (not selected_courses or quiz.get("course") in selected_courses) and
            (wk := quiz.get("week"))):
            weeks.add(wk)
    return sorted(weeks)


def get_categories_for(selected_levels, selected_semesters, selected_courses, selected_weeks):
    cats = set()
    for quiz in st.session_state.quizzes.values():
        match = True
        if selected_levels and quiz.get("level") not in selected_levels: match = False
        if selected_semesters and quiz.get("semester") not in selected_semesters: match = False
        if selected_courses and quiz.get("course") not in selected_courses: match = False
        if selected_weeks and quiz.get("week") not in selected_weeks: match = False
        if match and (cat := quiz.get("quiz_category")):
            cats.add(cat)
    return sorted(cats)


def get_subcategories_for_depts(selected_depts):
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
    all_depts = sorted(set(get_all_departments() | {"Uncategorized"}))

    with tab1:
        quiz_json = st.text_area("Quiz JSON", height=240, placeholder="Paste valid quiz JSON here...")
        quiz_title = st.text_input("Quiz title (optional)", key="new_quiz_title")

        department = st.selectbox("Department / Category", options=list(all_depts) + ["New department..."], key="new_quiz_dept_select")
        new_dept = ""
        if department == "New department...":
            new_dept = st.text_input("Enter new department name", key="new_dept_input").strip()
        final_dept = new_dept or department

        subcategory = st.text_input("Sub-category / Topic (optional)", key="new_quiz_subcat").strip()

        level = st.selectbox("Level", [""] + get_all_levels() + ["Other..."], key="new_level")
        if level == "Other...":
            level = st.text_input("Custom level", key="new_custom_level").strip()

        semester = st.selectbox("Semester", ["", "First Semester", "Second Semester", "Other..."], key="new_semester")
        if semester == "Other...":
            semester = st.text_input("Custom semester", key="new_custom_semester").strip()

        course = st.text_input("Course (e.g. CSC 101, MAT 111)", key="new_course").strip()

        week = st.text_input("Week (e.g. Week 3, Midterm)", key="new_week").strip()

        quiz_category = st.text_input("Quiz Category (e.g. Quiz 1, Past Questions)", key="new_quiz_cat").strip()

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
                if level:
                    data["level"] = level
                if semester:
                    data["semester"] = semester
                if course:
                    data["course"] = course
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
# Edit quiz form (admin only) — added course field
# ───────────────────────────────────────────────
def edit_quiz_form():
    if not st.session_state.get('edit_quiz_title'):
        return
    title = st.session_state.edit_quiz_title
    data = st.session_state.edit_quiz_data
    st.subheader(f"Editing Quiz: {title}")

    edited_title = st.text_input("Quiz Title", value=data.get("quiz_title", title), key="edit_title_input")

    all_depts = sorted(set(get_all_departments() | {"Uncategorized"}))
    current_dept = data.get("department") or data.get("category", "Uncategorized")
    dept_index = all_depts.index(current_dept) if current_dept in all_depts else 0

    department = st.selectbox("Department / Category", options=list(all_depts) + ["New department..."], index=dept_index, key="edit_dept_select")
    new_dept = ""
    if department == "New department...":
        new_dept = st.text_input("New department name", key="edit_new_dept_input").strip()
    final_dept = new_dept or department

    subcategory = st.text_input("Sub-category / Topic (optional)", value=data.get("subcategory", ""), key="edit_subcat_input")

    level_options = [""] + get_all_levels()
    current_level = data.get("level", "")
    if current_level and current_level not in level_options:
        level_options.append(current_level)
    level = st.selectbox("Level", level_options + ["Other..."], index=level_options.index(current_level) if current_level in level_options else 0, key="edit_level")
    if level == "Other...":
        level = st.text_input("Custom level", key="edit_custom_level").strip()

    semester_options = ["", "First Semester", "Second Semester"]
    current_sem = data.get("semester", "")
    semester = st.selectbox("Semester", semester_options + ["Other..."], index=semester_options.index(current_sem) if current_sem in semester_options else 0, key="edit_semester")
    if semester == "Other...":
        semester = st.text_input("Custom semester", key="edit_custom_semester").strip()

    course = st.text_input("Course", value=data.get("course", ""), key="edit_course").strip()

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

                if level:
                    new_data["level"] = level
                else:
                    new_data.pop("level", None)
                if semester:
                    new_data["semester"] = semester
                else:
                    new_data.pop("semester", None)
                if course:
                    new_data["course"] = course
                else:
                    new_data.pop("course", None)
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
# Organize & move quizzes (added course support)
# ───────────────────────────────────────────────
def organize_quizzes_section():
    st.subheader("Organize / Move Existing Quizzes")

    if not st.session_state.quizzes:
        st.info("No quizzes available yet.")
        return

    search_term = st.text_input("Filter by title", "").strip().lower()

    for title, quiz in sorted(st.session_state.quizzes.items()):
        if search_term and search_term not in title.lower():
            continue

        with st.expander(f"📄 {title}", expanded=False):
            st.caption("Current values:")
            st.markdown(f"""
            • **Level:** {quiz.get('level', '—')}  
            • **Semester:** {quiz.get('semester', '—')}  
            • **Course:** {quiz.get('course', '—')}  
            • **Week:** {quiz.get('week', '—')}  
            • **Category:** {quiz.get('quiz_category', '—')}
            """)

            st.divider()

            lvl_opts = [""] + get_all_levels()
            new_level = st.selectbox("Level", lvl_opts + ["Other..."], index=lvl_opts.index(quiz.get("level", "")) if quiz.get("level") in lvl_opts else 0, key=f"org_level_{title}")
            if new_level == "Other...":
                new_level = st.text_input("Custom level", key=f"org_lvl_custom_{title}").strip() or quiz.get("level", "")

            sem_opts = ["", "First Semester", "Second Semester"]
            new_sem = st.selectbox("Semester", sem_opts + ["Other..."], index=sem_opts.index(quiz.get("semester", "")) if quiz.get("semester") in sem_opts else 0, key=f"org_sem_{title}")
            if new_sem == "Other...":
                new_sem = st.text_input("Custom semester", key=f"org_sem_custom_{title}").strip() or quiz.get("semester", "")

            new_course = st.text_input("Course", value=quiz.get("course", ""), key=f"org_course_{title}").strip()

            new_week = st.text_input("Week", value=quiz.get("week", ""), key=f"org_week_{title}").strip()

            new_cat = st.text_input("Quiz Category", value=quiz.get("quiz_category", ""), key=f"org_cat_{title}").strip()

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
                    st.info("No changes made.")


# ───────────────────────────────────────────────
# Take quiz section (unchanged)
# ───────────────────────────────────────────────
# (your existing take_quiz_section() function remains here - no changes)


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

    selected_courses = []
    if selected_depts and selected_levels and selected_semesters:
        possible_courses = get_courses_for(selected_depts, selected_levels, selected_semesters)
        selected_courses = st.multiselect(
            "Course",
            options=possible_courses,
            default=[],
            placeholder="Select course(s)",
            key="course_multi"
        )

    selected_weeks = []
    if selected_depts and selected_levels and selected_semesters and selected_courses:
        selected_weeks = st.multiselect(
            "Week",
            options=get_weeks_for(selected_levels, selected_semesters, selected_courses),
            default=[],
            placeholder="Select week(s)",
            key="week_multi"
        )

    selected_categories = []
    if selected_depts and selected_levels and selected_semesters and selected_courses and selected_weeks:
        selected_categories = st.multiselect(
            "Quiz Category / Type",
            options=get_categories_for(selected_levels, selected_semesters, selected_courses, selected_weeks),
            default=[],
            placeholder="Select category",
            key="cat_multi"
        )

    st.session_state.update({
        'selected_departments': selected_depts,
        'selected_levels': selected_levels,
        'selected_semesters': selected_semesters,
        'selected_courses': selected_courses,
        'selected_weeks': selected_weeks,
        'selected_categories': selected_categories
    })

    st.header("Available Quizzes")

    # Progressive reveal — quizzes only shown after Course is selected
    if not selected_depts:
        st.info("Select at least one **department** to begin.")
    elif not selected_levels:
        st.info("Select **level(s)**.")
    elif not selected_semesters:
        st.info("Select **semester(s)**.")
    elif not selected_courses:
        st.info("Select **course(s)** to see available quizzes.")
    else:
        filtered = {}
        for title, quiz in st.session_state.quizzes.items():
            ok = True
            dept = quiz.get("department") or quiz.get("category", "Uncategorized")
            if selected_depts and dept not in selected_depts:
                ok = False
            if selected_levels and quiz.get("level") not in selected_levels:
                ok = False
            if selected_semesters and quiz.get("semester") not in selected_semesters:
                ok = False
            if selected_courses and quiz.get("course") not in selected_courses:
                ok = False
            if selected_weeks and quiz.get("week") not in selected_weeks:
                ok = False
            if selected_categories and quiz.get("quiz_category") not in selected_categories:
                ok = False

            if ok:
                parts = [p for p in [
                    quiz.get("level"),
                    quiz.get("semester"),
                    quiz.get("course"),
                    quiz.get("week"),
                    quiz.get("quiz_category")
                ] if p]
                label = title
                if parts:
                    label += " • " + " → ".join(parts)
                filtered[label] = title

        if not filtered:
            st.info("No quizzes match the selected filters.")
        else:
            st.caption(f"Found {len(filtered)} quiz{'zes' if len(filtered) != 1 else ''}")
            for label, real_title in sorted(filtered.items()):
                cols = st.columns([4, 1, 1])
                with cols[0]:
                    active = real_title == st.session_state.selected_quiz
                    if st.button(label, key=f"q_{real_title}",
                                 type="primary" if active else "secondary",
                                 use_container_width=True):
                        if not active:
                            st.session_state.selected_quiz = real_title
                            # Reset quiz attempt state
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
        with st.expander("🗂️ Organize & Move Quizzes", expanded=False):
            organize_quizzes_section()

        with st.expander("➕ Add New Quiz", expanded=False):
            submit_quiz_section()
    else:
        st.caption("Quiz creation & organization restricted to admin.")


# ── Main content ────────────────────────────────────────
if not st.session_state.selected_departments:
    st.info("Select at least one department from the sidebar to view available quizzes.")
elif st.session_state.selected_quiz:
    take_quiz_section()
else:
    st.info("Choose a quiz from the list in the sidebar.")


# ── Edit form ───────────────
if is_admin() and st.session_state.get('edit_quiz_title'):
    edit_quiz_form()