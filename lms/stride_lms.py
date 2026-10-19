import frappe
import hashlib
import hmac
import json as _json
from frappe import _
from frappe.utils import nowdate, flt, cint, fmt_money, getdate, date_diff
from frappe.rate_limiter import rate_limit
from lms.lms.utils import get_course_details,guest_access_allowed,get_membership,get_course_content_stats,get_lesson_index,get_outline_chapter,get_outline_lessons,get_scorm_files,get_completed_lessons,build_outline,get_instructors,get_course_fields,can_modify_course,update_course_filters,resolve_page_length,get_featured_courses,get_enrollment_details,get_course_card_details


ALLOWED_INSTRUCTOR_ROLES = {
    "Mentor",
    "College",
    "Industry",
    "Partner"
}


def validate_course_creator():
    user = frappe.session.user

    if not user or user == "Guest":
        return False, "Authentication required"

    roles = set(
        frappe.get_roles(user)
    )

    if not roles.intersection(ALLOWED_INSTRUCTOR_ROLES):
        return False, (
            "Only Mentor, College, Industry or Partner "
            "users can create courses"
        )

    return True, user

# ============================================================
# COMMON RESPONSE
# ============================================================

def success(data=None, message="Success"):
    return {
        "status": 200,
        "message": message,
        "data": data
    }


def error(message, status=400, data=None):
    frappe.local.response.http_status_code = status
    return {
        "status": status,
        "message": message,
        "data": data
    }


@frappe.whitelist()
def create_course(
    title,
    short_introduction=None,
    description=None,
    published=0,
    video_link=None,
    tags=None,
    category=None,
    image=None,
    card_gradient=None,
    published_on=None,
    upcoming=0,
    featured=0,
    disable_self_learning=0,
    enforce_lesson_completion=0,
    paid_course=0,
    paid_certificate=0,
    enable_certification=0,
    course_price=0,
    currency="INR",
    amount_usd=0,
    evaluator=None,
    timezone=None
):
    try:
        instructor = frappe.session.user

        if not instructor or instructor == "Guest":
            return error("Authenticated instructor required", 401)

        if not title:
            return error("Course title is required", 400)

        if not short_introduction:
            return error("Short introduction is required", 400)

        if not description:
            return error("Course description is required", 400)

        if frappe.db.exists("LMS Course", {"title": title}):
            return error("A course with this title already exists", 409)

        # Build course document
        course_data = {
            "doctype": "LMS Course",
            "title": title,
            "short_introduction": short_introduction,
            "description": description,
            "published": int(published),
            "video_link": video_link,
            "tags": tags,
            "category": category,
            "image": image,
            "card_gradient": card_gradient,
            "published_on": published_on,
            "upcoming": int(upcoming),
            "featured": int(featured),
            "disable_self_learning": int(disable_self_learning),
            "enforce_lesson_completion": int(enforce_lesson_completion),
            "paid_course": int(paid_course),
            "paid_certificate": int(paid_certificate),
            "enable_certification": int(enable_certification),
            "course_price": course_price,
            "currency": currency,
            "amount_usd": amount_usd,
            "evaluator": evaluator,
            "timezone": timezone,
            "instructors": [
                {
                    "instructor": instructor
                }
            ]
        }

        # Remove optional fields that were not supplied
        optional_fields = [
            "video_link",
            "tags",
            "category",
            "image",
            "card_gradient",
            "published_on",
            "evaluator",
            "timezone"
        ]

        for field in optional_fields:
            if course_data[field] is None:
                course_data.pop(field)

        doc = frappe.get_doc(course_data)

        doc.insert(ignore_permissions=True)

        frappe.db.commit()

        return success(
            doc.as_dict(),
            "Course created successfully"
        )

    except Exception as e:
        frappe.db.rollback()

        frappe.log_error(
            frappe.get_traceback(),
            "Create LMS Course"
        )

        return error(str(e), 500)

@frappe.whitelist()
def get_course(name):
    try:
        # Fetch course document
        course = frappe.get_doc("LMS Course", name)

        # Convert course document to dictionary
        course_data = course.as_dict()

        # Fetch chapters
        chapters = frappe.get_all(
            "Course Chapter",
            filters={"course": name},
            fields=["*"],
            order_by="idx asc"
        )

        # Add lessons to each chapter
        for chapter in chapters:
            chapter["lessons"] = frappe.get_all(
                "Course Lesson",
                filters={
                    "course": name,
                    "chapter": chapter["name"]
                },
                fields=["*"],
                order_by="idx asc"
            )

        # Preserve the existing response structure
        course_data["chapters"] = chapters

        return success(
            course_data,
            "Course, chapters and lessons fetched successfully"
        )

    except frappe.DoesNotExistError:
        return error("Course not found", 404)

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Get Course With Chapters And Lessons"
        )
        return error(str(e), 500)

@frappe.whitelist()
def update_course(
    name,
    title=None,
    short_introduction=None,
    description=None,
    published=None,
    video_link=None,
    tags=None,
    category=None,
    image=None,
    card_gradient=None,
    published_on=None,
    upcoming=None,
    featured=None,
    disable_self_learning=None,
    enforce_lesson_completion=None,
    paid_course=None,
    paid_certificate=None,
    enable_certification=None,
    course_price=None,
    currency=None,
    amount_usd=None,
    evaluator=None,
    timezone=None
):
    try:
        # --------------------------------
        # Validate logged-in course creator
        # --------------------------------
        valid, result = validate_course_creator()

        if not valid:
            return error(result, 403)

        instructor = result

        # --------------------------------
        # Get course
        # --------------------------------
        doc = frappe.get_doc("LMS Course", name)

        # --------------------------------
        # Update basic fields
        # --------------------------------
        if title is not None:
            doc.title = title

        if short_introduction is not None:
            doc.short_introduction = short_introduction

        if description is not None:
            doc.description = description

        if published is not None:
            doc.published = int(published)

        # --------------------------------
        # Update course details
        # --------------------------------
        if video_link is not None:
            doc.video_link = video_link

        if tags is not None:
            doc.tags = tags

        if category is not None:
            doc.category = category

        if image is not None:
            doc.image = image

        if card_gradient is not None:
            doc.card_gradient = card_gradient

        if published_on is not None:
            doc.published_on = published_on

        # --------------------------------
        # Update course settings
        # --------------------------------
        if upcoming is not None:
            doc.upcoming = int(upcoming)

        if featured is not None:
            doc.featured = int(featured)

        if disable_self_learning is not None:
            doc.disable_self_learning = int(disable_self_learning)

        if enforce_lesson_completion is not None:
            doc.enforce_lesson_completion = int(
                enforce_lesson_completion
            )

        # --------------------------------
        # Update pricing and certification
        # --------------------------------
        if paid_course is not None:
            doc.paid_course = int(paid_course)

        if paid_certificate is not None:
            doc.paid_certificate = int(paid_certificate)

        if enable_certification is not None:
            doc.enable_certification = int(
                enable_certification
            )

        if course_price is not None:
            doc.course_price = course_price

        if currency is not None:
            doc.currency = currency

        if amount_usd is not None:
            doc.amount_usd = amount_usd

        if evaluator is not None:
            doc.evaluator = evaluator

        if timezone is not None:
            doc.timezone = timezone

        # --------------------------------
        # Save document
        # --------------------------------
        doc.save(ignore_permissions=True)

        frappe.db.commit()

        # --------------------------------
        # Response
        # --------------------------------
        return success(
            doc.as_dict(),
            "Course updated successfully"
        )

    except frappe.DoesNotExistError:
        return error(
            "Course not found",
            404
        )

    except Exception as e:
        frappe.db.rollback()

        frappe.log_error(
            frappe.get_traceback(),
            "Update LMS Course"
        )

        return error(
            str(e),
            500
        )

@frappe.whitelist()
def delete_course(name):

    try:
        valid, result = validate_course_creator()

        if not valid:
            return error(result, 403)

        if not frappe.db.exists("LMS Course", name):
            return error("Course not found", 404)

        frappe.delete_doc(
            "LMS Course",
            name,
            ignore_permissions=True
        )

        frappe.db.commit()

        return success(
            {"name": name},
            "Course deleted successfully"
        )

    except frappe.DoesNotExistError:
        return error("Course not found", 404)

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Delete LMS Course"
        )

        return error(str(e), 500)

# ============================================================
# CHAPTER
# ============================================================

@frappe.whitelist()
def create_chapter(
    course,
    title,
    idx=1
):

    try:
        valid, result = validate_course_creator()

        if not valid:
            return error(result, 403)

        if not course:
            return error("Course is required", 400)

        if not title:
            return error("Chapter title is required", 400)

        if not frappe.db.exists("LMS Course", course):
            return error("Course not found", 404)

        doc = frappe.get_doc({
            "doctype": "Course Chapter",
            "course": course,
            "title": title,
            "idx": idx
        })

        doc.insert(
            ignore_permissions=True
        )

        frappe.db.commit()

        return success(
            doc.as_dict(),
            "Chapter created successfully"
        )

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Create LMS Chapter"
        )

        return error(str(e), 500)


@frappe.whitelist()
def get_chapter(name):
    try:

        doc = frappe.get_doc(
            "Course Chapter",
            name
        )

        return success(
            doc.as_dict(),
            "Chapter fetched successfully"
        )

    except frappe.DoesNotExistError:
        return error("Chapter not found", 404)

    except Exception as e:
        return error(str(e), 500)


@frappe.whitelist()
def get_chapters(course):
    try:

        chapters = frappe.get_all(
            "Course Chapter",
            filters={
                "course": course
            },
            fields=[
                "name",
                "title",
                "course",
                "idx"
            ],
            order_by="idx asc"
        )

        return success(
            chapters,
            "Chapters fetched successfully"
        )

    except Exception as e:
        return error(str(e), 500)

@frappe.whitelist()
def update_chapter(
    name,
    title=None,
    idx=None
):

    try:
        valid, result = validate_course_creator()

        if not valid:
            return error(result, 403)

        doc = frappe.get_doc(
            "Course Chapter",
            name
        )

        if title is not None:
            doc.title = title

        if idx is not None:
            doc.idx = idx

        doc.save(
            ignore_permissions=True
        )

        frappe.db.commit()

        return success(
            doc.as_dict(),
            "Chapter updated successfully"
        )

    except frappe.DoesNotExistError:
        return error("Chapter not found", 404)

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Update LMS Chapter"
        )

        return error(str(e), 500)


@frappe.whitelist()
def delete_chapter(name):

    try:
        valid, result = validate_course_creator()

        if not valid:
            return error(result, 403)

        if not frappe.db.exists(
            "Course Chapter",
            name
        ):
            return error(
                "Chapter not found",
                404
            )

        frappe.delete_doc(
            "Course Chapter",
            name,
            ignore_permissions=True
        )

        frappe.db.commit()

        return success(
            {"name": name},
            "Chapter deleted successfully"
        )

    except frappe.DoesNotExistError:
        return error("Chapter not found", 404)

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Delete LMS Chapter"
        )

        return error(str(e), 500)
# ============================================================
# LESSON
# ============================================================

import json


import frappe
import json


@frappe.whitelist()
def create_lesson(
    course,
    chapter,
    title,
    include_in_preview=0,
    is_scorm_package=0,
    content=None,
    body=None,
    instructor_content=None,
    instructor_notes=None,
    youtube=None,
    quiz_id=None,
    question=None,
    file_type=None
):
    try:
        # --------------------------------
        # Authentication / Role Validation
        # --------------------------------
        valid, result = validate_course_creator()

        if not valid:
            return error(result, 403)

        # --------------------------------
        # Required Fields
        # --------------------------------
        if not course:
            return error("Course is required", 400)

        if not chapter:
            return error("Chapter is required", 400)

        if not title:
            return error("Lesson title is required", 400)

        # --------------------------------
        # Validate Course
        # --------------------------------
        if not frappe.db.exists("LMS Course", course):
            return error("Course not found", 404)

        # --------------------------------
        # Validate Chapter
        # --------------------------------
        if not frappe.db.exists("Course Chapter", chapter):
            return error("Chapter not found", 404)

        # --------------------------------
        # Validate Chapter Belongs to Course
        # --------------------------------
        chapter_course = frappe.db.get_value(
            "Course Chapter",
            chapter,
            "course"
        )

        if chapter_course != course:
            return error(
                "Chapter does not belong to this course",
                400
            )

        # --------------------------------
        # Validate JSON Content
        # --------------------------------
        if content is not None:
            if isinstance(content, (dict, list)):
                content = json.dumps(content)

            elif not isinstance(content, str):
                return error(
                    "Content must be a JSON object, array, or string",
                    400
                )

            try:
                json.loads(content)

            except json.JSONDecodeError:
                return error(
                    "Invalid lesson content. Content must be valid JSON.",
                    400
                )

        # --------------------------------
        # Validate File Type
        # --------------------------------
        allowed_file_types = ["Image", "Document", "PDF"]

        if file_type and file_type not in allowed_file_types:
            return error(
                "File Type must be Image, Document, or PDF",
                400
            )

        # --------------------------------
        # Prepare Lesson Document
        # --------------------------------
        lesson_data = {
            "doctype": "Course Lesson",
            "course": course,
            "chapter": chapter,
            "title": title,
            "include_in_preview": include_in_preview,
            "content": content,
            "body": body,
            "instructor_content": instructor_content,
            "instructor_notes": instructor_notes,
            "youtube": youtube,
            "quiz_id": quiz_id,
            "question": question,
            "file_type": file_type
        }

        # is_scorm_package is fetched from the chapter
        # in your DocType, so it is not set directly.

        doc = frappe.get_doc(lesson_data)

        doc.insert(ignore_permissions=True)

        frappe.db.commit()

        return success(
            doc.as_dict(),
            "Lesson created successfully"
        )

    except frappe.DoesNotExistError:
        frappe.db.rollback()

        return error(
            "Course, chapter, or lesson does not exist",
            404
        )

    except Exception as e:
        frappe.db.rollback()

        frappe.log_error(
            frappe.get_traceback(),
            "Create LMS Lesson"
        )

        return error(str(e), 500)

@frappe.whitelist(allow_guest=True)
def get_lesson(name):
    try:
        member = frappe.session.user
        doc = frappe.get_doc(
            "Course Lesson",
            name
        )

        # Enforce paywall & enrollment if not a preview lesson
        if not cint(doc.include_in_preview):
            if not member or member == "Guest":
                return error("Authentication required to access this lesson.", 401)

            roles = set(frappe.get_roles(member))
            is_instructor = frappe.db.exists(
                "Course Instructor",
                {"parent": doc.course, "instructor": member, "parenttype": "LMS Course"}
            )
            is_privileged = bool(roles.intersection({"Administrator", "System Manager", "Moderator"})) or is_instructor

            if not is_privileged:
                # 1. Direct course enrollment
                is_enrolled = frappe.db.exists(
                    "LMS Enrollment",
                    {"course": doc.course, "member": member}
                )

                # 2. Batch enrollment (cohort contains this course)
                if not is_enrolled:
                    is_enrolled = bool(frappe.db.sql("""
                        SELECT be.name FROM `tabLMS Batch Enrollment` be
                        JOIN `tabBatch Course` bc ON bc.parent = be.batch
                        WHERE be.member = %s AND bc.course = %s
                    """, (member, doc.course)))

                if not is_enrolled:
                    is_paid = cint(frappe.db.get_value("LMS Course", doc.course, "paid_course"))
                    if is_paid:
                        return error(
                            "You must purchase this course to access this lesson.",
                            403,
                            data={
                                "requires_purchase": True,
                                "is_paid": True,
                                "course": doc.course,
                                "lesson": doc.name
                            }
                        )
                    else:
                        return error(
                            "Please enroll in this course to start learning.",
                            403,
                            data={
                                "requires_enrollment": True,
                                "is_paid": False,
                                "course": doc.course,
                                "lesson": doc.name
                            }
                        )

        return success(
            doc.as_dict(),
            "Lesson fetched successfully"
        )

    except frappe.DoesNotExistError:
        return error("Lesson not found", 404)

    except Exception as e:
        return error(str(e), 500)


@frappe.whitelist()
def get_lessons(
    course=None,
    chapter=None
):

    try:
        filters = {}

        if course:
            filters["course"] = course

        if chapter:
            filters["chapter"] = chapter

        lessons = frappe.get_all(
            "Course Lesson",
            filters=filters,
            fields=[
                "name",
                "title",
                "course",
                "chapter",
                "idx",
                "creation",
                "modified"
            ],
            order_by="idx asc"
        )

        return success(
            lessons,
            "Lessons fetched successfully"
        )

    except Exception as e:
        return error(str(e), 500)


@frappe.whitelist()
def update_lesson(
    name,
    title=None,
    content=None,
    idx=None
):

    try:
        valid, result = validate_course_creator()

        if not valid:
            return error(result, 403)

        doc = frappe.get_doc(
            "Course Lesson",
            name
        )

        if title is not None:
            doc.title = title

        if content is not None:
            doc.content = content

        if idx is not None:
            doc.idx = idx

        doc.save(
            ignore_permissions=True
        )

        frappe.db.commit()

        return success(
            doc.as_dict(),
            "Lesson updated successfully"
        )

    except frappe.DoesNotExistError:
        return error(
            "Lesson not found",
            404
        )

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Update LMS Lesson"
        )

        return error(str(e), 500)

@frappe.whitelist()
def delete_lesson(name):

    try:
        valid, result = validate_course_creator()

        if not valid:
            return error(result, 403)

        if not frappe.db.exists(
            "Course Lesson",
            name
        ):
            return error(
                "Lesson not found",
                404
            )

        frappe.delete_doc(
            "Course Lesson",
            name,
            ignore_permissions=True
        )

        frappe.db.commit()

        return success(
            {"name": name},
            "Lesson deleted successfully"
        )

    except frappe.DoesNotExistError:
        return error(
            "Lesson not found",
            404
        )

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Delete LMS Lesson"
        )

        return error(str(e), 500)


# ============================================================
# QUIZ
# ============================================================

@frappe.whitelist()
def create_quiz(
    title,
    course=None,
    max_attempts=0,
    duration=None,
    passing_percentage=50,
    show_answers=0
):

    try:
        valid, result = validate_course_creator()

        if not valid:
            return error(result, 403)

        if not title:
            return error(
                "Quiz title is required",
                400
            )

        if course and not frappe.db.exists(
            "LMS Course",
            course
        ):
            return error(
                "Course not found",
                404
            )

        doc = frappe.get_doc({
            "doctype": "LMS Quiz",
            "title": title,
            "course": course,
            "max_attempts": max_attempts,
            "duration": duration,
            "passing_percentage": passing_percentage,
            "show_answers": show_answers
        })

        doc.insert(
            ignore_permissions=True
        )

        frappe.db.commit()

        return success(
            doc.as_dict(),
            "Quiz created successfully"
        )

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Create LMS Quiz"
        )

        return error(str(e), 500)


@frappe.whitelist()
def get_quiz(name):

    try:
        doc = frappe.get_doc(
            "LMS Quiz",
            name
        )

        return success(
            doc.as_dict(),
            "Quiz fetched successfully"
        )

    except frappe.DoesNotExistError:
        return error(
            "Quiz not found",
            404
        )

    except Exception as e:
        return error(str(e), 500)


@frappe.whitelist()
def get_quizzes(course=None):

    try:
        filters = {}

        if course:
            filters["course"] = course

        quizzes = frappe.get_all(
            "LMS Quiz",
            filters=filters,
            fields=[
                "*"
            ],
            order_by="creation desc"
        )

        return success(
            quizzes,
            "Quizzes fetched successfully"
        )

    except Exception as e:
        return error(str(e), 500)


@frappe.whitelist()
def update_quiz(
    name,
    title=None,
    max_attempts=None,
    duration=None,
    passing_percentage=None,
    show_answers=None
):

    try:
        valid, result = validate_course_creator()

        if not valid:
            return error(result, 403)

        doc = frappe.get_doc(
            "LMS Quiz",
            name
        )

        fields = {
            "title": title,
            "max_attempts": max_attempts,
            "duration": duration,
            "passing_percentage": passing_percentage,
            "show_answers": show_answers
        }

        for field, value in fields.items():
            if value is not None:
                setattr(
                    doc,
                    field,
                    value
                )

        doc.save(
            ignore_permissions=True
        )

        frappe.db.commit()

        return success(
            doc.as_dict(),
            "Quiz updated successfully"
        )

    except frappe.DoesNotExistError:
        return error(
            "Quiz not found",
            404
        )

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Update LMS Quiz"
        )

        return error(str(e), 500)


@frappe.whitelist()
def delete_quiz(name):

    try:
        valid, result = validate_course_creator()

        if not valid:
            return error(result, 403)

        if not frappe.db.exists(
            "LMS Quiz",
            name
        ):
            return error(
                "Quiz not found",
                404
            )

        frappe.delete_doc(
            "LMS Quiz",
            name,
            ignore_permissions=True
        )

        frappe.db.commit()

        return success(
            {"name": name},
            "Quiz deleted successfully"
        )

    except frappe.DoesNotExistError:
        return error(
            "Quiz not found",
            404
        )

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Delete LMS Quiz"
        )

        return error(str(e), 500)


# ============================================================
# BATCH
# ============================================================



@frappe.whitelist()
def create_batch(
    title,
    start_date,
    end_date,
    start_time,
    end_time,
    timezone,
    description,
    published=0,
    allow_self_enrollment=0,
    allow_future=0,
    seat_count=None,
    category=None,
    evaluation=0,
    evaluation_end_date=None,
    certification=0,
    medium="Online",
    batch_details=None,
    batch_details_raw=None,
    conferencing_provider=None,
    zoom_account=None,
    google_meet_account=None,
    show_live_class=0,
    video_link=None,
    meta_image=None,
    paid_batch=0,
    amount=None,
    currency=None,
    amount_usd=None,
    timetable_template=None,
    confirmation_email_template=None,
    courses=None,
    instructors=None,
    assessment=None,
    timetable=None,
    timetable_legends=None
):
    """
    Create LMS Batch.

    API:
    POST /api/method/stridenex_app.api_stridenex_app.lms.create_batch
    """

    try:
        # ---------------------------------------------------------
        # Required fields
        # ---------------------------------------------------------

        if not title:
            frappe.throw(_("Title is required."))

        if not start_date:
            frappe.throw(_("Start Date is required."))

        if not end_date:
            frappe.throw(_("End Date is required."))

        if not start_time:
            frappe.throw(_("Start Time is required."))

        if not end_time:
            frappe.throw(_("End Time is required."))

        if not timezone:
            frappe.throw(_("Timezone is required."))

        if not description:
            frappe.throw(_("Description is required."))

        # ---------------------------------------------------------
        # Validate dates
        # ---------------------------------------------------------

        if start_date > end_date:
            frappe.throw(
                _("Start Date cannot be after End Date.")
            )

        # ---------------------------------------------------------
        # Duplicate title check
        # ---------------------------------------------------------

        if frappe.db.exists("LMS Batch", {"title": title}):
            frappe.throw(
                _("A batch with title '{0}' already exists.").format(title)
            )

        # ---------------------------------------------------------
        # Create Batch
        # ---------------------------------------------------------

        doc = frappe.new_doc("LMS Batch")

        doc.title = title
        doc.start_date = start_date
        doc.end_date = end_date
        doc.start_time = start_time
        doc.end_time = end_time
        doc.timezone = timezone
        doc.description = description

        doc.published = published
        doc.allow_self_enrollment = allow_self_enrollment
        doc.allow_future = allow_future
        if seat_count is not None:
            doc.seat_count = seat_count
        if category:
            doc.category = category
        doc.evaluation = evaluation
        if evaluation_end_date:
            doc.evaluation_end_date = evaluation_end_date
        doc.certification = certification
        if medium:
            doc.medium = medium
        if batch_details is not None:
            doc.batch_details = batch_details
        if batch_details_raw is not None:
            doc.batch_details_raw = batch_details_raw
        if conferencing_provider:
            doc.conferencing_provider = conferencing_provider
        if zoom_account:
            doc.zoom_account = zoom_account

        if google_meet_account:
            doc.google_meet_account = google_meet_account

        doc.show_live_class = show_live_class

        if video_link:
            doc.video_link = video_link

        if meta_image:
            doc.meta_image = meta_image

        doc.paid_batch = paid_batch

        if amount is not None:
            doc.amount = amount

        if currency:
            doc.currency = currency

        if amount_usd is not None:
            doc.amount_usd = amount_usd

        if timetable_template:
            doc.timetable_template = timetable_template

        if confirmation_email_template:
            doc.confirmation_email_template = confirmation_email_template

        # ---------------------------------------------------------
        # Courses
        # ---------------------------------------------------------

        if courses:
            if isinstance(courses, str):
                courses = frappe.parse_json(courses)
            for row in courses:
                if not row.get("course"):
                    frappe.throw(_("Course is required."))
                child = doc.append("courses", {})
                child.course = row.get("course")

        # ---------------------------------------------------------
        # Instructors
        # ---------------------------------------------------------

        if instructors:
            if isinstance(instructors, str):
                instructors = frappe.parse_json(instructors)
            for row in instructors:
                if not row.get("instructor"):
                    frappe.throw(_("Instructor is required."))
                child = doc.append("instructors", {})
                child.instructor = row.get("instructor")

        # ---------------------------------------------------------
        # Assessment
        # ---------------------------------------------------------

        if assessment:
            if isinstance(assessment, str):
                assessment = frappe.parse_json(assessment)
            for row in assessment:
                child = doc.append("assessment", {})
                if row.get("assessment"):
                    child.assessment = row.get("assessment")

        # ---------------------------------------------------------
        # Timetable
        # ---------------------------------------------------------

        if timetable:
            if isinstance(timetable, str):
                timetable = frappe.parse_json(timetable)
            for row in timetable:
                child = doc.append("timetable", {})
                if row.get("date"):
                    child.date = row.get("date")
                if row.get("day") is not None:
                    child.day = row.get("day")
                if row.get("from_time"):
                    child.from_time = row.get("from_time")
                if row.get("to_time"):
                    child.to_time = row.get("to_time")
                if row.get("instructor"):
                    child.instructor = row.get("instructor")
                if row.get("room"):
                    child.room = row.get("room")

        # ---------------------------------------------------------
        # Timetable Legends
        # ---------------------------------------------------------

        if timetable_legends:
            if isinstance(timetable_legends, str):
                timetable_legends = frappe.parse_json(
                    timetable_legends
                )

            for row in timetable_legends:

                child = doc.append("timetable_legends", {})

                if row.get("legend"):
                    child.legend = row.get("legend")

                if row.get("color"):
                    child.color = row.get("color")

        # ---------------------------------------------------------
        # Insert
        # ---------------------------------------------------------

        doc.insert(ignore_permissions=True)

        frappe.db.commit()

        return {
            "success": True,
            "message": "Batch created successfully.",
            "data": {
                "name": doc.name,
                "title": doc.title,
                "published": doc.published,
                "description": doc.description,
                "start_date": doc.start_date,
                "end_date": doc.end_date,
                "start_time": doc.start_time,
                "end_time": doc.end_time,
                "timezone": doc.timezone,
                "allow_self_enrollment": doc.allow_self_enrollment,
                "allow_future": doc.allow_future,
                "seat_count": doc.seat_count,
                "category": doc.category,
                "evaluation": doc.evaluation,
                "evaluation_end_date": doc.evaluation_end_date,
                "certification": doc.certification,
                "medium": doc.medium,
                "batch_details": doc.batch_details,
                "batch_details_raw": doc.batch_details_raw,
                "conferencing_provider": doc.conferencing_provider,
                "zoom_account": doc.zoom_account,
                "google_meet_account": doc.google_meet_account,
                "show_live_class": doc.show_live_class,
                "video_link": doc.video_link,
                "meta_image": doc.meta_image,
                "paid_batch": doc.paid_batch,
                "amount": doc.amount,
                "currency": doc.currency,
                "amount_usd": doc.amount_usd,
                "timetable_template": doc.timetable_template,
                "confirmation_email_template": (
                    doc.confirmation_email_template
                ),
                "courses": [
                    {
                        "name": row.name,
                        "course": row.course
                    }
                    for row in doc.courses
                ],
                "instructors": [
                    {
                        "name": row.name,
                        "instructor": row.instructor
                    }
                    for row in doc.instructors
                ],
                "assessment": [
                    {
                        "name": row.name,
                        "assessment": row.assessment
                    }
                    for row in doc.assessment
                ],
                "timetable": [
                    {
                        "name": row.name,
                        "date": getattr(row, "date", None),
                        "day": getattr(row, "day", None),
                        "from_time": getattr(
                            row, "from_time", None
                        ),
                        "to_time": getattr(
                            row, "to_time", None
                        ),
                        "instructor": getattr(
                            row, "instructor", None
                        ),
                        "room": getattr(row, "room", None)
                    }
                    for row in doc.timetable
                ],
                "timetable_legends": [
                    {
                        "name": row.name,
                        "legend": row.legend,
                        "color": row.color
                    }
                    for row in doc.timetable_legends
                ]
            }
        }

    except Exception as e:

        frappe.db.rollback()

        frappe.log_error(
            frappe.get_traceback(),
            "Create LMS Batch Error"
        )

        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist()
def get_batch_details(batch):
    """
    Get complete LMS Batch information.
    """

    if not batch:
        frappe.throw(_("Batch is required."))

    if not frappe.db.exists("LMS Batch", batch):
        frappe.throw(_("LMS Batch {0} does not exist.").format(batch))

    # ---------------------------------------------------------
    # 1. Main Batch
    # ---------------------------------------------------------

    batch_doc = frappe.get_doc("LMS Batch", batch)

    data = {
        "name": batch_doc.name,
        "title": batch_doc.title,
        "published": batch_doc.published,
        "description": batch_doc.description,
        "start_date": batch_doc.start_date,
        "end_date": batch_doc.end_date,
        "start_time": batch_doc.start_time,
        "end_time": batch_doc.end_time,
        "timezone": batch_doc.timezone,
        "allow_self_enrollment": batch_doc.allow_self_enrollment,
        "allow_future": batch_doc.allow_future,
        "seat_count": batch_doc.seat_count,
        "category": batch_doc.category,
        "evaluation": batch_doc.evaluation,
        "evaluation_end_date": batch_doc.evaluation_end_date,
        "certification": batch_doc.certification,
        "medium": batch_doc.medium,
        "batch_details": batch_doc.batch_details,
        "batch_details_raw": batch_doc.batch_details_raw,
        "conferencing_provider": batch_doc.conferencing_provider,
        "zoom_account": batch_doc.zoom_account,
        "google_meet_account": batch_doc.google_meet_account,
        "show_live_class": batch_doc.show_live_class,
        "video_link": batch_doc.video_link,
        "meta_image": batch_doc.meta_image,
        "paid_batch": batch_doc.paid_batch,
        "amount": batch_doc.amount,
        "currency": batch_doc.currency,
        "amount_usd": batch_doc.amount_usd,
        "timetable_template": batch_doc.timetable_template,
        "confirmation_email_template": (
            batch_doc.confirmation_email_template
        ),
        "created": batch_doc.creation,
        "modified": batch_doc.modified
    }

    # ---------------------------------------------------------
    # 2. Courses
    # ---------------------------------------------------------

    courses = []

    for row in batch_doc.courses:

        course_data = {
            "name": row.name,
            "course": row.course,
            "course_title": None
        }

        if row.course:
            course_data["course_title"] = frappe.db.get_value(
                "LMS Course",
                row.course,
                "title"
            )

        courses.append(course_data)

    data["courses"] = courses

    # ---------------------------------------------------------
    # 3. Instructors
    # ---------------------------------------------------------

    instructors = []

    for row in batch_doc.instructors:

        instructor_data = {
            "name": row.name,
            "instructor": getattr(row, "instructor", None)
        }

        instructor = instructor_data["instructor"]

        if instructor:
            instructor_data["instructor_name"] = frappe.db.get_value(
                "User",
                instructor,
                "full_name"
            )

            instructor_data["user_image"] = frappe.db.get_value(
                "User",
                instructor,
                "user_image"
            )

        instructors.append(instructor_data)

    data["instructors"] = instructors

    # ---------------------------------------------------------
    # 4. Assessment
    # ---------------------------------------------------------

    assessments = []

    for row in batch_doc.assessment:

        assessments.append({
            "name": row.name,
            "assessment": getattr(row, "assessment", None)
        })

    data["assessment"] = assessments

    # ---------------------------------------------------------
    # 5. Timetable
    # ---------------------------------------------------------

    timetable = []

    for row in batch_doc.timetable:

        timetable.append({
            "name": row.name,
            "day": getattr(row, "day", None),
            "from_time": getattr(row, "from_time", None),
            "to_time": getattr(row, "to_time", None),
            "instructor": getattr(row, "instructor", None),
            "room": getattr(row, "room", None)
        })

    data["timetable"] = timetable

    # ---------------------------------------------------------
    # 6. Timetable Legends
    # ---------------------------------------------------------

    timetable_legends = []

    for row in batch_doc.timetable_legends:

        timetable_legends.append({
            "name": row.name,
            "legend": getattr(row, "legend", None),
            "color": getattr(row, "color", None)
        })

    data["timetable_legends"] = timetable_legends

    # ---------------------------------------------------------
    # 7. Enrollment information
    # ---------------------------------------------------------

    total_enrolled = frappe.db.count(
        "LMS Batch Enrollment",
        {
            "batch": batch
        }
    )

    data["enrollment"] = {
        "total_enrolled": total_enrolled,
        "seat_count": batch_doc.seat_count,
        "available_seats": (
            batch_doc.seat_count - total_enrolled
            if batch_doc.seat_count
            else None
        )
    }

    # ---------------------------------------------------------
    # 8. Feedback Summary
    # ---------------------------------------------------------

    feedback = frappe.db.sql(
        """
        SELECT
            COUNT(*) AS total_reviews,
            COALESCE(AVG(content), 0) AS content_rating,
            COALESCE(AVG(instructors), 0) AS instructor_rating,
            COALESCE(AVG(value), 0) AS value_rating
        FROM `tabLMS Batch Feedback`
        WHERE batch = %s
        """,
        (batch,),
        as_dict=True
    )[0]

    total_reviews = feedback.total_reviews or 0

    if total_reviews:
        overall_rating = (
            float(feedback.content_rating)
            + float(feedback.instructor_rating)
            + float(feedback.value_rating)
        ) / 3
    else:
        overall_rating = 0

    data["feedback"] = {
        "total_reviews": total_reviews,
        "content_rating": round(
            float(feedback.content_rating), 2
        ),
        "instructor_rating": round(
            float(feedback.instructor_rating), 2
        ),
        "value_rating": round(
            float(feedback.value_rating), 2
        ),
        "overall_rating": round(
            overall_rating, 2
        )
    }

    # ---------------------------------------------------------
    # Final Response
    # ---------------------------------------------------------

    return {
        "success": True,
        "message": "Batch details fetched successfully.",
        "data": data
    }
@frappe.whitelist()
def get_batch(name):

    try:
        doc = frappe.get_doc(
            "LMS Batch",
            name
        )

        return success(
            doc.as_dict(),
            "Batch fetched successfully"
        )

    except frappe.DoesNotExistError:
        return error(
            "Batch not found",
            404
        )

    except Exception as e:
        return error(str(e), 500)


@frappe.whitelist()
def get_batches():

    try:
        batches = frappe.get_all(
            "LMS Batch",
            fields=[
                "name",
                "title",
                "start_date",
                "end_date",
                "start_time",
                "end_time",
                "seat_count",
                "published",
                "creation",
                "modified"
            ],
            order_by="creation desc"
        )

        return success(
            batches,
            "Batches fetched successfully"
        )

    except Exception as e:
        return error(str(e), 500)
    

import frappe
from frappe import _


@frappe.whitelist()
def update_batch(
    batch,
    title=None,
    published=None,
    description=None,
    start_date=None,
    end_date=None,
    start_time=None,
    end_time=None,
    timezone=None,
    allow_self_enrollment=None,
    allow_future=None,
    seat_count=None,
    category=None,
    evaluation=None,
    evaluation_end_date=None,
    certification=None,
    medium=None,
    batch_details=None,
    batch_details_raw=None,
    conferencing_provider=None,
    zoom_account=None,
    google_meet_account=None,
    show_live_class=None,
    video_link=None,
    meta_image=None,
    paid_batch=None,
    amount=None,
    currency=None,
    amount_usd=None,
    timetable_template=None,
    confirmation_email_template=None,
    courses=None,
    instructors=None,
    assessment=None,
    timetable=None,
    timetable_legends=None
):
    """
    Update LMS Batch and its child tables.

    API:
    POST /api/method/stridenex_app.api_stridenex_app.lms.update_batch
    """

    try:
        if not batch:
            frappe.throw(_("Batch name is required."))

        if not frappe.db.exists("LMS Batch", batch):
            frappe.throw(_("Batch {0} does not exist.").format(batch))

        doc = frappe.get_doc("LMS Batch", batch)

        # ---------------------------------------------------------
        # Main Batch Fields
        # ---------------------------------------------------------

        fields = {
            "title": title,
            "published": published,
            "description": description,
            "start_date": start_date,
            "end_date": end_date,
            "start_time": start_time,
            "end_time": end_time,
            "timezone": timezone,
            "allow_self_enrollment": allow_self_enrollment,
            "allow_future": allow_future,
            "seat_count": seat_count,
            "category": category,
            "evaluation": evaluation,
            "evaluation_end_date": evaluation_end_date,
            "certification": certification,
            "medium": medium,
            "batch_details": batch_details,
            "batch_details_raw": batch_details_raw,
            "conferencing_provider": conferencing_provider,
            "zoom_account": zoom_account,
            "google_meet_account": google_meet_account,
            "show_live_class": show_live_class,
            "video_link": video_link,
            "meta_image": meta_image,
            "paid_batch": paid_batch,
            "amount": amount,
            "currency": currency,
            "amount_usd": amount_usd,
            "timetable_template": timetable_template,
            "confirmation_email_template": confirmation_email_template
        }

        for fieldname, value in fields.items():
            if value is not None:
                setattr(doc, fieldname, value)

        # ---------------------------------------------------------
        # Courses
        # ---------------------------------------------------------

        if courses is not None:
            if isinstance(courses, str):
                courses = frappe.parse_json(courses)

            doc.set("courses", [])

            for row in courses:
                child = doc.append("courses", {})

                if row.get("name"):
                    child.name = row.get("name")

                if row.get("course") is not None:
                    child.course = row.get("course")

        # ---------------------------------------------------------
        # Instructors
        # ---------------------------------------------------------

        if instructors is not None:
            if isinstance(instructors, str):
                instructors = frappe.parse_json(instructors)

            doc.set("instructors", [])

            for row in instructors:
                child = doc.append("instructors", {})

                if row.get("name"):
                    child.name = row.get("name")

                if row.get("instructor") is not None:
                    child.instructor = row.get("instructor")

        # ---------------------------------------------------------
        # Assessment
        # ---------------------------------------------------------

        if assessment is not None:
            if isinstance(assessment, str):
                assessment = frappe.parse_json(assessment)

            doc.set("assessment", [])

            for row in assessment:
                child = doc.append("assessment", {})

                if row.get("name"):
                    child.name = row.get("name")

                if row.get("assessment") is not None:
                    child.assessment = row.get("assessment")

        # ---------------------------------------------------------
        # Timetable
        # ---------------------------------------------------------

        if timetable is not None:
            if isinstance(timetable, str):
                timetable = frappe.parse_json(timetable)

            doc.set("timetable", [])

            for row in timetable:
                child = doc.append("timetable", {})

                if row.get("name"):
                    child.name = row.get("name")

                if row.get("date") is not None:
                    child.date = row.get("date")

                if row.get("day") is not None:
                    child.day = row.get("day")

                if row.get("from_time") is not None:
                    child.from_time = row.get("from_time")

                if row.get("to_time") is not None:
                    child.to_time = row.get("to_time")

                if row.get("instructor") is not None:
                    child.instructor = row.get("instructor")

                if row.get("room") is not None:
                    child.room = row.get("room")

        # ---------------------------------------------------------
        # Timetable Legends
        # ---------------------------------------------------------

        if timetable_legends is not None:
            if isinstance(timetable_legends, str):
                timetable_legends = frappe.parse_json(timetable_legends)

            doc.set("timetable_legends", [])

            for row in timetable_legends:
                child = doc.append("timetable_legends", {})

                if row.get("name"):
                    child.name = row.get("name")

                if row.get("legend") is not None:
                    child.legend = row.get("legend")

                if row.get("color") is not None:
                    child.color = row.get("color")

        # ---------------------------------------------------------
        # Validate Date Range
        # ---------------------------------------------------------

        if doc.start_date and doc.end_date:
            if doc.start_date > doc.end_date:
                frappe.throw(
                    _("Start Date cannot be after End Date.")
                )

        # ---------------------------------------------------------
        # Save
        # ---------------------------------------------------------

        doc.save(ignore_permissions=True)

        frappe.db.commit()

        return {
            "success": True,
            "message": "Batch updated successfully.",
            "data": {
                "name": doc.name,
                "title": doc.title,
                "published": doc.published,
                "description": doc.description,
                "start_date": doc.start_date,
                "end_date": doc.end_date,
                "start_time": doc.start_time,
                "end_time": doc.end_time,
                "timezone": doc.timezone,
                "allow_self_enrollment": doc.allow_self_enrollment,
                "allow_future": doc.allow_future,
                "seat_count": doc.seat_count,
                "category": doc.category,
                "evaluation": doc.evaluation,
                "evaluation_end_date": doc.evaluation_end_date,
                "certification": doc.certification,
                "medium": doc.medium,
                "batch_details": doc.batch_details,
                "batch_details_raw": doc.batch_details_raw,
                "conferencing_provider": doc.conferencing_provider,
                "zoom_account": doc.zoom_account,
                "google_meet_account": doc.google_meet_account,
                "show_live_class": doc.show_live_class,
                "video_link": doc.video_link,
                "meta_image": doc.meta_image,
                "paid_batch": doc.paid_batch,
                "amount": doc.amount,
                "currency": doc.currency,
                "amount_usd": doc.amount_usd,
                "timetable_template": doc.timetable_template,
                "confirmation_email_template": doc.confirmation_email_template
            }
        }

    except Exception as e:
        frappe.db.rollback()

        frappe.log_error(
            frappe.get_traceback(),
            "Update LMS Batch Error"
        )

        return {
            "success": False,
            "message": str(e)
        }

@frappe.whitelist()
def delete_batch(name):

    try:
        valid, result = validate_course_creator()

        if not valid:
            return error(result, 403)

        if not frappe.db.exists(
            "LMS Batch",
            name
        ):
            return error(
                "Batch not found",
                404
            )

        frappe.delete_doc(
            "LMS Batch",
            name,
            ignore_permissions=True
        )

        frappe.db.commit()

        return success(
            {"name": name},
            "Batch deleted successfully"
        )

    except frappe.DoesNotExistError:
        return error(
            "Batch not found",
            404
        )

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Delete LMS Batch"
        )

        return error(str(e), 500)

# ============================================================
# ENROLLMENT
# ============================================================

@frappe.whitelist()
def enroll_student(course):

    try:
        member = frappe.session.user

        if not member or member == "Guest":
            return error(
                "Authentication required",
                401
            )

        if not frappe.db.exists(
            "LMS Course",
            course
        ):
            return error(
                "Course not found",
                404
            )

        is_published = cint(frappe.db.get_value("LMS Course", course, "published"))
        roles = set(frappe.get_roles(member)) if member else set()
        is_admin_user = bool(roles.intersection({"Administrator", "System Manager", "Moderator", "Course Creator"}))
        if not is_published and not is_admin_user:
            return error(
                "You cannot enroll in an unpublished course.",
                400
            )

        is_paid = cint(frappe.db.get_value("LMS Course", course, "paid_course"))
        if is_paid:
            return error(
                "This is a paid course. Please complete payment to enroll.",
                400,
                data={"is_paid": True, "requires_payment": True, "course": course}
            )

        existing = frappe.db.exists(
            "LMS Enrollment",
            {
                "course": course,
                "member": member
            }
        )

        if existing:
            return error(
                "Student is already enrolled",
                409
            )

        doc = frappe.get_doc({
            "doctype": "LMS Enrollment",
            "course": course,
            "member": member
        })

        doc.insert(
            ignore_permissions=True
        )

        frappe.db.commit()

        return success(
            doc.as_dict(),
            "Student enrolled successfully"
        )

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Enroll Student"
        )

        return error(str(e), 500)

@frappe.whitelist()
def get_enrollments(
    course=None,
    member=None
):

    try:
        filters = {}

        if course:
            filters["course"] = course

        if member:
            filters["member"] = member

        enrollments = frappe.get_all(
            "LMS Enrollment",
            filters=filters,
            fields="*",
            order_by="creation desc"
        )

        return success(
            enrollments,
            "Enrollments fetched successfully"
        )

    except Exception as e:
        return error(
            str(e),
            500
        )


# ============================================================
# CERTIFICATE
# ============================================================

@frappe.whitelist()
def create_certificate(
    member,
    course,
    issue_date=None
):

    try:
        valid, result = validate_course_creator()

        if not valid:
            return error(
                result,
                403
            )

        if not member:
            return error(
                "Member is required",
                400
            )

        if not course:
            return error(
                "Course is required",
                400
            )

        if not frappe.db.exists(
            "LMS Course",
            course
        ):
            return error(
                "Course not found",
                404
            )

        if not issue_date:
            issue_date = nowdate()

        existing = frappe.db.exists(
            "LMS Certificate",
            {
                "member": member,
                "course": course
            }
        )

        if existing:
            return error(
                "Certificate already exists",
                409
            )

        doc = frappe.get_doc({
            "doctype": "LMS Certificate",
            "member": member,
            "course": course,
            "issue_date": issue_date
        })

        doc.insert(
            ignore_permissions=True
        )

        frappe.db.commit()

        return success(
            doc.as_dict(),
            "Certificate created successfully"
        )

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Create LMS Certificate"
        )

        return error(
            str(e),
            500
        )


@frappe.whitelist()
def get_certificate(name):

    try:

        doc = frappe.get_doc(
            "LMS Certificate",
            name
        )

        return success(
            doc.as_dict(),
            "Certificate fetched successfully"
        )

    except frappe.DoesNotExistError:
        return error(
            "Certificate not found",
            404
        )

    except Exception as e:
        return error(str(e), 500)


@frappe.whitelist()
def get_certificates(member=None):

    try:
        filters = {}

        if member:
            filters["member"] = member

        certificates = frappe.get_all(
            "LMS Certificate",
            filters=filters,
            fields="*",
            order_by="creation desc"
        )

        return success(
            certificates,
            "Certificates fetched successfully"
        )

    except Exception as e:
        return error(
            str(e),
            500
        )

@frappe.whitelist()
def get_question(name):
    try:
        if not name:
            return error("Question name is required", 400)

        # name can be LMS Question name
        if not frappe.db.exists("LMS Question", name):
            return error("Question not found", 404)

        doc = frappe.get_doc("LMS Question", name)

        data = {
            "name": doc.name,
            "question": doc.question,
            "type": doc.type,
            "multiple": doc.multiple,

            "options": [
                {
                    "option": doc.option_1,
                    "is_correct": doc.is_correct_1,
                    "explanation": doc.explanation_1
                },
                {
                    "option": doc.option_2,
                    "is_correct": doc.is_correct_2,
                    "explanation": doc.explanation_2
                },
                {
                    "option": doc.option_3,
                    "is_correct": doc.is_correct_3,
                    "explanation": doc.explanation_3
                },
                {
                    "option": doc.option_4,
                    "is_correct": doc.is_correct_4,
                    "explanation": doc.explanation_4
                }
            ],

            "possible_answers": [
                doc.possibility_1,
                doc.possibility_2,
                doc.possibility_3,
                doc.possibility_4
            ]
        }

        # Remove empty options
        data["options"] = [
            option for option in data["options"]
            if option["option"]
        ]

        # Remove empty possible answers
        data["possible_answers"] = [
            answer
            for answer in data["possible_answers"]
            if answer
        ]

        return success(
            data,
            "Question fetched successfully"
        )

    except frappe.DoesNotExistError:
        return error("Question not found", 404)

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Get LMS Question Error"
        )

        return error(str(e), 500)


@frappe.whitelist()
def create_question(
    question,
    type,
    multiple=0,
    option_1=None,
    is_correct_1=0,
    explanation_1=None,
    option_2=None,
    is_correct_2=0,
    explanation_2=None,
    option_3=None,
    is_correct_3=0,
    explanation_3=None,
    option_4=None,
    is_correct_4=0,
    explanation_4=None,
    possibility_1=None,
    possibility_2=None,
    possibility_3=None,
    possibility_4=None
):
    try:
        # -----------------------------
        # Validation
        # -----------------------------
        if not question:
            return error("Question is required", 400)

        if not type:
            return error("Question type is required", 400)

        allowed_types = [
            "Choices",
            "User Input",
            "Open Ended"
        ]

        if type not in allowed_types:
            return error(
                "Invalid question type. Allowed: Choices, User Input, Open Ended",
                400
            )

        # -----------------------------
        # Validate Choices
        # -----------------------------
        if type == "Choices":

            if not option_1:
                return error(
                    "Option 1 is required for Choices question",
                    400
                )

            if not option_2:
                return error(
                    "Option 2 is required for Choices question",
                    400
                )

            # At least one correct answer
            correct_answers = [
                is_correct_1,
                is_correct_2,
                is_correct_3,
                is_correct_4
            ]

            if not any(correct_answers):
                return error(
                    "At least one correct answer is required",
                    400
                )

            # If multiple = 0, only one answer can be correct
            if not int(multiple):
                if sum(int(x) for x in correct_answers) > 1:
                    return error(
                        "Only one correct answer is allowed when multiple is disabled",
                        400
                    )

        # -----------------------------
        # Validate User Input
        # -----------------------------
        if type == "User Input":

            if not possibility_1:
                return error(
                    "Possible Answer 1 is required for User Input question",
                    400
                )

        # -----------------------------
        # Create LMS Question
        # -----------------------------
        doc = frappe.get_doc({
            "doctype": "LMS Question",

            "question": question,
            "type": type,
            "multiple": int(multiple),

            "option_1": option_1,
            "is_correct_1": int(is_correct_1),
            "explanation_1": explanation_1,

            "option_2": option_2,
            "is_correct_2": int(is_correct_2),
            "explanation_2": explanation_2,

            "option_3": option_3,
            "is_correct_3": int(is_correct_3),
            "explanation_3": explanation_3,

            "option_4": option_4,
            "is_correct_4": int(is_correct_4),
            "explanation_4": explanation_4,

            "possibility_1": possibility_1,
            "possibility_2": possibility_2,
            "possibility_3": possibility_3,
            "possibility_4": possibility_4
        })

        doc.insert(ignore_permissions=True)

        frappe.db.commit()

        return success(
            doc.as_dict(),
            "Question created successfully"
        )

    except Exception as e:
        frappe.db.rollback()

        frappe.log_error(
            frappe.get_traceback(),
            "Create LMS Question Error"
        )

        return error(str(e), 500)

@frappe.whitelist()
def get_questions(
    page=1,
    page_size=20,
    question_type=None
):
    try:
        page = int(page)
        page_size = int(page_size)

        if page < 1:
            page = 1

        if page_size < 1:
            page_size = 20

        if page_size > 100:
            page_size = 100

        start = (page - 1) * page_size

        filters = {}

        if question_type:
            filters["type"] = question_type

        questions = frappe.get_all(
            "LMS Quiz Question",
            filters=filters,
            fields=[
                "*"
            ],
            order_by="creation desc",
            start=start,
            page_length=page_size
        )

        total = frappe.db.count(
            "LMS Quiz Question",
            filters=filters
        )

        return success(
            {
                "questions": questions,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total": total,
                    "total_pages": (total + page_size - 1) // page_size
                }
            },
            "Questions fetched successfully"
        )

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Get LMS Questions Error"
        )

        return error(str(e), 500)


# ============================================================
# CREATE LMS CERTIFICATE EVALUATION
# ============================================================

@frappe.whitelist()
def create_certificate_evaluation(
    member,
    course,
    date,
    start_time,
    status,
    batch_name=None,
    evaluator=None,
    end_time=None,
    rating=None,
    summary=None
):
    try:

        # -----------------------------
        # Required fields
        # -----------------------------

        if not member:
            return error("Member is required", 400)

        if not course:
            return error("Course is required", 400)

        if not date:
            return error("Date is required", 400)

        if not start_time:
            return error("Start Time is required", 400)

        if not status:
            return error("Status is required", 400)

        # -----------------------------
        # Validate status
        # -----------------------------

        valid_statuses = [
            "Pending",
            "In Progress",
            "Pass",
            "Fail"
        ]

        if status not in valid_statuses:
            return error(
                "Invalid status. Allowed values: Pending, In Progress, Pass, Fail",
                400
            )

        # -----------------------------
        # Validate Member
        # -----------------------------

        if not frappe.db.exists("User", member):
            return error(
                f"Member '{member}' does not exist",
                404
            )

        # -----------------------------
        # Validate Course
        # -----------------------------

        if not frappe.db.exists("LMS Course", course):
            return error(
                f"Course '{course}' does not exist",
                404
            )

        # -----------------------------
        # Validate Batch
        # -----------------------------

        if batch_name:
            if not frappe.db.exists("LMS Batch", batch_name):
                return error(
                    f"Batch '{batch_name}' does not exist",
                    404
                )

        # -----------------------------
        # Validate Evaluator
        # -----------------------------

        if evaluator:
            if not frappe.db.exists("User", evaluator):
                return error(
                    f"Evaluator '{evaluator}' does not exist",
                    404
                )

        # -----------------------------
        # Rating required when Pass
        # -----------------------------

        if status == "Pass" and rating is None:
            return error(
                "Rating is required when status is Pass",
                400
            )

        # -----------------------------
        # Summary required when
        # status is Pass or Fail
        # -----------------------------

        if status in ["Pass", "Fail"] and not summary:
            return error(
                "Summary is required when status is Pass or Fail",
                400
            )

        # -----------------------------
        # Create document
        # -----------------------------

        doc = frappe.get_doc({
            "doctype": "LMS Certificate Evaluation",

            "member": member,
            "course": course,
            "batch_name": batch_name,

            "evaluator": evaluator,

            "date": date,
            "start_time": start_time,
            "end_time": end_time,

            "rating": rating,
            "status": status,
            "summary": summary
        })

        doc.insert(ignore_permissions=True)

        frappe.db.commit()

        return success(
            doc.as_dict(),
            "Certificate evaluation created successfully"
        )

    except Exception as e:

        frappe.log_error(
            frappe.get_traceback(),
            "Create LMS Certificate Evaluation"
        )

        return error(str(e), 500)


# ============================================================
# GET LMS CERTIFICATE EVALUATION
# ============================================================

@frappe.whitelist()
def get_certificate_evaluation(name):

    try:

        if not name:
            return error(
                "Certificate Evaluation name is required",
                400
            )

        if not frappe.db.exists(
            "LMS Certificate Evaluation",
            name
        ):
            return error(
                "Certificate evaluation not found",
                404
            )

        doc = frappe.get_doc(
            "LMS Certificate Evaluation",
            name
        )

        return success(
            doc.as_dict(),
            "Certificate evaluation fetched successfully"
        )

    except Exception as e:

        frappe.log_error(
            frappe.get_traceback(),
            "Get LMS Certificate Evaluation"
        )

        return error(str(e), 500)


# ============================================================
# UPDATE LMS CERTIFICATE EVALUATION
# ============================================================

@frappe.whitelist()
def update_certificate_evaluation(
    name,
    member=None,
    course=None,
    date=None,
    start_time=None,
    status=None,
    batch_name=None,
    evaluator=None,
    end_time=None,
    rating=None,
    summary=None
):

    try:

        if not name:
            return error(
                "Certificate Evaluation name is required",
                400
            )

        if not frappe.db.exists(
            "LMS Certificate Evaluation",
            name
        ):
            return error(
                "Certificate evaluation not found",
                404
            )

        doc = frappe.get_doc(
            "LMS Certificate Evaluation",
            name
        )

        # -----------------------------
        # Update only supplied fields
        # -----------------------------

        if member is not None:

            if not frappe.db.exists("User", member):
                return error(
                    f"Member '{member}' does not exist",
                    404
                )

            doc.member = member

        if course is not None:

            if not frappe.db.exists("LMS Course", course):
                return error(
                    f"Course '{course}' does not exist",
                    404
                )

            doc.course = course

        if batch_name is not None:

            if batch_name and not frappe.db.exists(
                "LMS Batch",
                batch_name
            ):
                return error(
                    f"Batch '{batch_name}' does not exist",
                    404
                )

            doc.batch_name = batch_name

        if evaluator is not None:

            if evaluator and not frappe.db.exists(
                "User",
                evaluator
            ):
                return error(
                    f"Evaluator '{evaluator}' does not exist",
                    404
                )

            doc.evaluator = evaluator

        if date is not None:
            doc.date = date

        if start_time is not None:
            doc.start_time = start_time

        if end_time is not None:
            doc.end_time = end_time

        if status is not None:

            valid_statuses = [
                "Pending",
                "In Progress",
                "Pass",
                "Fail"
            ]

            if status not in valid_statuses:
                return error(
                    "Invalid status. Allowed values: Pending, In Progress, Pass, Fail",
                    400
                )

            doc.status = status

        if rating is not None:
            doc.rating = rating

        if summary is not None:
            doc.summary = summary

        # -----------------------------
        # Validate final document state
        # -----------------------------

        if doc.status == "Pass" and doc.rating is None:
            return error(
                "Rating is required when status is Pass",
                400
            )

        if doc.status in ["Pass", "Fail"] and not doc.summary:
            return error(
                "Summary is required when status is Pass or Fail",
                400
            )

        doc.save(ignore_permissions=True)

        frappe.db.commit()

        return success(
            doc.as_dict(),
            "Certificate evaluation updated successfully"
        )

    except Exception as e:

        frappe.log_error(
            frappe.get_traceback(),
            "Update LMS Certificate Evaluation"
        )

        return error(str(e), 500)


# ============================================================
# DELETE LMS CERTIFICATE EVALUATION
# ============================================================

@frappe.whitelist()
def delete_certificate_evaluation(name):

    try:

        if not name:
            return error(
                "Certificate Evaluation name is required",
                400
            )

        if not frappe.db.exists(
            "LMS Certificate Evaluation",
            name
        ):
            return error(
                "Certificate evaluation not found",
                404
            )

        frappe.delete_doc(
            "LMS Certificate Evaluation",
            name,
            ignore_permissions=True
        )

        frappe.db.commit()

        return success(
            {
                "name": name
            },
            "Certificate evaluation deleted successfully"
        )

    except Exception as e:

        frappe.log_error(
            frappe.get_traceback(),
            "Delete LMS Certificate Evaluation"
        )

        return error(str(e), 500)


# ============================================================
# LIST LMS CERTIFICATE EVALUATIONS
# ============================================================

@frappe.whitelist()
def list_certificate_evaluations(
    member=None,
    course=None,
    batch_name=None,
    evaluator=None,
    status=None,
    limit=20,
    start=0
):

    try:

        filters = {}

        if member:
            filters["member"] = member

        if course:
            filters["course"] = course

        if batch_name:
            filters["batch_name"] = batch_name

        if evaluator:
            filters["evaluator"] = evaluator

        if status:
            filters["status"] = status

        records = frappe.get_all(
            "LMS Certificate Evaluation",
            filters=filters,
            fields=[
                "name",
                "member",
                "member_name",
                "course",
                "batch_name",
                "evaluator",
                "evaluator_name",
                "date",
                "start_time",
                "end_time",
                "rating",
                "status",
                "summary",
                "creation",
                "modified"
            ],
            order_by="modified desc",
            limit_start=int(start),
            limit_page_length=int(limit)
        )

        return success(
            records,
            "Certificate evaluations fetched successfully"
        )

    except Exception as e:

        frappe.log_error(
            frappe.get_traceback(),
            "List LMS Certificate Evaluations"
        )

        return error(str(e), 500)




@frappe.whitelist()
def get_course_progress(
    name=None,
    member=None,
    member_name=None,
    status=None,
    lesson=None,
    chapter=None,
    course=None,
    is_scorm_chapter=None,
    limit=20,
    start=0
):
    try:
        # ------------------------------------------------
        # Filters
        # ------------------------------------------------
        filters = {}

        if name:
            filters["name"] = name

        if member:
            filters["member"] = member

        if member_name:
            filters["member_name"] = member_name

        if status:
            filters["status"] = status

        if lesson:
            filters["lesson"] = lesson

        if chapter:
            filters["chapter"] = chapter

        if course:
            filters["course"] = course

        if is_scorm_chapter is not None:
            filters["is_scorm_chapter"] = is_scorm_chapter

        # ------------------------------------------------
        # Validate pagination
        # ------------------------------------------------
        limit = int(limit)
        start = int(start)

        if limit <= 0:
            limit = 20

        if start < 0:
            start = 0

        # ------------------------------------------------
        # Fetch records
        # ------------------------------------------------
        records = frappe.get_all(
            "LMS Course Progress",
            filters=filters,
            fields=[
                "name",
                "member",
                "member_name",
                "status",
                "lesson",
                "chapter",
                "course",
                "is_scorm_chapter",
                "scorm_content",
                "creation",
                "modified"
            ],
            order_by="modified desc",
            limit_start=start,
            limit_page_length=limit
        )

        # ------------------------------------------------
        # Total records
        # ------------------------------------------------
        total = frappe.db.count(
            "LMS Course Progress",
            filters=filters
        )

        # ------------------------------------------------
        # Response
        # ------------------------------------------------
        return {
            "status": 200,
            "message": "Course progress list fetched successfully",
            "data": {
                "records": records,
                "total": total,
                "limit": limit,
                "start": start
            }
        }

    except Exception as e:

        frappe.log_error(
            frappe.get_traceback(),
            "Get LMS Course Progress List"
        )

        frappe.local.response.http_status_code = 500

        return {
            "status": 500,
            "message": str(e),
            "data": None
        }

@frappe.whitelist(allow_guest=True)
@rate_limit(limit=500, seconds=60 * 60)
def get_batch_courses(batch: str) -> list:
	if not guest_access_allowed():
		return []

	courses = []
	course_list = frappe.get_all("Batch Course", {"parent": batch}, ["name", "course"])

	for course in course_list:
		details = get_course_details(course.course)
		if details.get("name"):
			details.batch_course = course.name
			courses.append(details)

	return courses

@frappe.whitelist(allow_guest=True)
@rate_limit(limit=500, seconds=60 * 60)
def get_course_completion_data():
	all_membership = frappe.db.count("LMS Enrollment")
	completed = frappe.db.count("LMS Enrollment", {"progress": ["like", "%100%"]})

	return [
		{"label": "Completed", "value": completed},
		{"label": "In Progress", "value": all_membership - completed},
	]
@frappe.whitelist(allow_guest=True)  # nosemgrep: frappe-semgrep-rules.rules.security.guest-whitelisted-method
@rate_limit(limit=500, seconds=60 * 60)
def get_course_details(course: str):
	if not guest_access_allowed():
		return {}

	is_course_published = frappe.db.get_value("LMS Course", course, "published")
	membership = get_membership(course)
	if not is_course_published and not can_modify_course(course) and not membership:
		return {}

	fields = get_course_fields()
	course_details = frappe.db.get_value(
		"LMS Course",
		course,
		fields,
		as_dict=1,
	)
	
	if not course_details:
		return {}

	course_details.instructors = get_instructors("LMS Course", course_details.name)
	course_details.membership = membership
	course_details.rating_count = frappe.db.count("LMS Course Review", {"course": course})
	course_details.update(get_course_content_stats(course))
	# course_details.is_instructor = is_instructor(course_details.name)
	if course_details.paid_course or course_details.paid_certificate:
		"""course_details.course_price, course_details.currency = check_multicurrency(
				course_details.course_price, course_details.currency, None, course_details.amount_usd
		)"""
		course_details.price = fmt_money(course_details.course_price, 0, course_details.currency)

	if frappe.session.user == "Guest":
		course_details.is_instructor = False

	if course_details.membership and course_details.membership.current_lesson:
		from lms.lms.permissions import get_lesson_gate

		_locked, resume = get_lesson_gate(course)
		course_details.current_lesson = get_lesson_index(resume or course_details.membership.current_lesson)

	return course_details

@frappe.whitelist(allow_guest=True)  
def get_course_outline(course: str, progress: bool = False) -> list:
	"""Returns the course outline."""

	if not guest_access_allowed():
		return []

	chapters = get_outline_chapter(course)
	if not chapters:
		return []

	lesson_rows = get_outline_lessons([c.name for c in chapters])
	files_by_name = get_scorm_files(chapters)
	completed = get_completed_lessons(course, lesson_rows) if progress else set()

	from lms.lms.permissions import enforces_lesson_completion

	enforce = enforces_lesson_completion(course) if progress else False

	return build_outline(chapters, lesson_rows, files_by_name, completed, progress, enforce)


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=500, seconds=60 * 60)
def get_reviews(course: str):
	reviews = frappe.get_all(
		"LMS Course Review",
		{"course": course},
		["review", "rating", "owner", "creation"],
		order_by="creation desc",
	)

	out_of_ratings = frappe.db.get_all(
		"DocField", {"parent": "LMS Course Review", "fieldtype": "Rating"}, ["options"]
	)
	out_of_ratings = (len(out_of_ratings) and out_of_ratings[0].options) or 5
	for review in reviews:
		review.rating = review.rating * out_of_ratings
		review.owner_details = frappe.db.get_value(
			"User", review.owner, ["username", "full_name", "user_image"], as_dict=True
		)

	return reviews

@frappe.whitelist(allow_guest=True)  # nosemgrep: frappe-semgrep-rules.rules.security.guest-whitelisted-method
@rate_limit(limit=500, seconds=60 * 60)
def get_courses(filters: dict = None, start: int = 0, limit_page_length: int | str = None) -> list:
	"""Returns the list of courses."""

	if not guest_access_allowed():
		return []

	if not filters:
		filters = {}

	filters, or_filters, show_featured = update_course_filters(filters)
	fields = get_course_fields()
	page_length = resolve_page_length(limit_page_length)
	start = cint(start)

	
	featured = (
		get_featured_courses(filters.copy(), or_filters, fields, start + page_length) if show_featured else []
	)
	courses = featured[start : start + page_length]
	remaining = page_length - len(courses)

	if remaining > 0:
		courses = courses + frappe.get_all(
			"LMS Course",
			filters=filters,
			fields=fields,
			or_filters=or_filters,
			order_by="enrollments desc",
			start=max(start - len(featured), 0),
			page_length=remaining,
		)

	courses = get_enrollment_details(courses)
	courses = get_course_card_details(courses)
	return courses


# ============================================================
# PAYMENT MODULE — Razorpay Integration
# ============================================================

# ── private helpers ──────────────────────────────────────────

def _get_razorpay_client():
    """Return (razorpay.Client, api_key, api_secret) from Razorpay Settings."""
    import razorpay
    rzp = frappe.get_doc("Razorpay Settings")
    secret = rzp.get_password(fieldname="api_secret", raise_exception=False)
    return razorpay.Client(auth=(rzp.api_key, secret)), rzp.api_key, secret


def _check_enrollment(item_type, item_id, member):
    """Return (is_enrolled: bool, message: str)."""
    if item_type == "course":
        enrolled = frappe.db.exists("LMS Enrollment", {"course": item_id, "member": member})
        return bool(enrolled), "You are already enrolled in this course."
    elif item_type == "batch":
        enrolled = frappe.db.exists("LMS Batch Enrollment", {"batch": item_id, "member": member})
        return bool(enrolled), "You are already enrolled in this batch."
    elif item_type == "certificate":
        purchased = frappe.db.exists(
            "LMS Enrollment",
            {"course": item_id, "member": member, "purchased_certificate": 1},
        )
        return bool(purchased), "You have already purchased the certificate for this course."
    return False, ""


def _validate_batch_access(item_id):
    """Return (ok: bool, message: str). Checks seats and start date."""
    batch = frappe.db.get_value(
        "LMS Batch",
        item_id,
        ["seat_count", "start_date", "end_date", "paid_batch"],
        as_dict=True,
    )
    if not batch:
        return False, "Batch not found."

    if batch.seat_count:
        enrolled_count = frappe.db.count("LMS Batch Enrollment", {"batch": item_id})
        if enrolled_count >= cint(batch.seat_count):
            return False, "This batch is sold out."

    if batch.end_date and date_diff(batch.end_date, nowdate()) < 0:
        return False, "This batch has already ended and is no longer available for purchase."
    elif not batch.end_date and batch.start_date and date_diff(batch.start_date, nowdate()) < 0:
        return False, "This batch has already started and is no longer available for purchase."

    return True, ""


def _get_saved_address(member):
    """Return saved billing address for member or empty dict."""
    address = frappe.db.get_value(
        "Address",
        {"email_id": member},
        [
            "address_title as billing_name",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "country",
            "pincode",
            "phone",
        ],
        as_dict=True,
    )
    return address or {}


def _save_billing_address(address_data, member):
    """Upsert billing address for member; return address name."""
    filters = {"email_id": member}
    if frappe.db.exists("Address", filters):
        doc = frappe.get_last_doc("Address", filters=filters)
    else:
        doc = frappe.new_doc("Address")

    full_name = frappe.db.get_value("User", member, "full_name") or address_data.get("billing_name", "")
    address_line1 = address_data.get("address_line1") or address_data.get("city") or "Online"
    doc.update(address_data)
    doc.update({
        "address_title": full_name,
        "address_type": "Billing",
        "is_primary_address": 1,
        "email_id": member,
        "address_line1": address_line1,
    })
    doc.flags.ignore_mandatory = True
    doc.save(ignore_permissions=True)
    return doc.name


def _create_razorpay_order(amount_inr, currency, receipt, client):
    """Create a Razorpay order and return the order dict (contains 'id')."""
    amount_paise = cint(round(flt(amount_inr) * 100))
    order = client.order.create(data={
        "amount": amount_paise,
        "currency": currency or "INR",
        "receipt": receipt,
        "payment_capture": 1,
    })
    return order


def _record_lms_payment(member, address_name, address_data, doctype, docname,
                        amount, original_amount, currency,
                        discount_amount=0, amount_with_gst=0,
                        coupon=None, coupon_code=None,
                        payment_for_certificate=0):
    """Insert and return a new LMS Payment document."""
    source_val = address_data.get("source") or "Website"
    if str(source_val).strip().lower() == "web":
        source_val = "Web" if frappe.db.exists("LMS Source", "Web") else "Website"
    elif not frappe.db.exists("LMS Source", source_val):
        source_val = "Website" if frappe.db.exists("LMS Source", "Website") else "Web"

    pay_doc = frappe.new_doc("LMS Payment")
    pay_doc.update({
        "member": member,
        "billing_name": address_data.get("billing_name", ""),
        "address": address_name,
        "amount": amount,
        "original_amount": original_amount,
        "currency": currency,
        "discount_amount": discount_amount,
        "amount_with_gst": amount_with_gst,
        "gstin": address_data.get("gstin", ""),
        "pan": address_data.get("pan", ""),
        "source": source_val,
        "payment_for_document_type": doctype,
        "payment_for_document": docname,
        "payment_for_certificate": payment_for_certificate,
        "member_consent": address_data.get("member_consent", 0),
        "payment_received": 0,
    })
    if coupon_code and coupon:
        pay_doc.update({"coupon": coupon, "coupon_code": coupon_code})
    pay_doc.flags.ignore_mandatory = True
    pay_doc.save(ignore_permissions=True)
    return pay_doc


def _execute_enrollment_for_payment(payment_name: str):
    """
    Safely and deterministically enroll the paying learner (pay_doc.member)
    for the course, batch, or program associated with the given LMS Payment.
    Bypasses permission constraints that fail under webhook or guest contexts.
    """
    pay_doc = frappe.get_doc("LMS Payment", payment_name)
    member = pay_doc.member
    doc_type = pay_doc.payment_for_document_type
    doc_name = pay_doc.payment_for_document

    if pay_doc.payment_for_certificate:
        from lms.lms.utils import update_certificate_purchase
        update_certificate_purchase(doc_name, payment_name)
        return

    if doc_type == "LMS Course":
        if not frappe.db.exists("LMS Enrollment", {"member": member, "course": doc_name}):
            enrollment = frappe.new_doc("LMS Enrollment")
            enrollment.member = member
            enrollment.course = doc_name
            enrollment.payment = pay_doc.name
            enrollment.member_type = "Student"
            enrollment.role = "Member"
            enrollment.flags.ignore_permissions = True
            enrollment.flags.ignore_mandatory = True
            enrollment.flags.ignore_validate = True
            enrollment.insert(ignore_permissions=True)
        else:
            enr_name = frappe.db.get_value("LMS Enrollment", {"member": member, "course": doc_name}, "name")
            if enr_name:
                frappe.db.set_value("LMS Enrollment", enr_name, "payment", pay_doc.name)

    elif doc_type == "LMS Batch":
        if not frappe.db.exists("LMS Batch Enrollment", {"member": member, "batch": doc_name}):
            batch_enr = frappe.new_doc("LMS Batch Enrollment")
            batch_enr.member = member
            batch_enr.batch = doc_name
            batch_enr.payment = pay_doc.name
            batch_enr.source = pay_doc.source or "Website"
            batch_enr.flags.ignore_permissions = True
            batch_enr.flags.ignore_mandatory = True
            batch_enr.flags.ignore_validate = True
            batch_enr.insert(ignore_permissions=True)
        else:
            b_enr_name = frappe.db.get_value("LMS Batch Enrollment", {"member": member, "batch": doc_name}, "name")
            if b_enr_name:
                frappe.db.set_value("LMS Batch Enrollment", b_enr_name, "payment", pay_doc.name)

        # Batch child courses: enroll member in each of them!
        batch_courses = frappe.get_all("Batch Course", filters={"parent": doc_name}, pluck="course")
        for course_id in batch_courses:
            if not frappe.db.exists("LMS Enrollment", {"member": member, "course": course_id}):
                c_enr = frappe.new_doc("LMS Enrollment")
                c_enr.member = member
                c_enr.course = course_id
                c_enr.enrollment_from_batch = doc_name
                c_enr.payment = pay_doc.name
                c_enr.member_type = "Student"
                c_enr.role = "Member"
                c_enr.flags.ignore_permissions = True
                c_enr.flags.ignore_mandatory = True
                c_enr.flags.ignore_validate = True
                c_enr.insert(ignore_permissions=True)

    elif doc_type == "LMS Program":
        if not frappe.db.exists("LMS Program Member", {"member": member, "parent": doc_name}):
            prog_mem = frappe.new_doc("LMS Program Member")
            prog_mem.member = member
            prog_mem.parent = doc_name
            prog_mem.parenttype = "LMS Program"
            prog_mem.parentfield = "program_members"
            prog_mem.flags.ignore_permissions = True
            prog_mem.insert(ignore_permissions=True)

        prog_courses = frappe.get_all("LMS Program Course", filters={"parent": doc_name}, pluck="course")
        for c in prog_courses:
            if not frappe.db.exists("LMS Enrollment", {"member": member, "course": c}):
                c_enr = frappe.new_doc("LMS Enrollment")
                c_enr.member = member
                c_enr.course = c
                c_enr.payment = pay_doc.name
                c_enr.member_type = "Student"
                c_enr.role = "Member"
                c_enr.flags.ignore_permissions = True
                c_enr.flags.ignore_mandatory = True
                c_enr.flags.ignore_validate = True
                c_enr.insert(ignore_permissions=True)

    if pay_doc.coupon:
        try:
            from lms.lms.utils import update_coupon_redemption
            update_coupon_redemption(pay_doc)
        except Exception:
            pass

    frappe.db.commit()


# ── public whitelisted API ───────────────────────────────────

@frappe.whitelist(allow_guest=True)
def get_checkout_summary(item_type, item_id, coupon_code=None, country=None):
    """
    Return pricing, discount, GST totals, and saved billing address.

    item_type : "course" | "batch" | "certificate"
    item_id   : LMS Course name or LMS Batch name
    """
    try:
        member = frappe.session.user
        is_guest = not member or member == "Guest"

        item_type = item_type.lower().strip()
        doctype = "LMS Batch" if item_type == "batch" else "LMS Course"

        if not frappe.db.exists(doctype, item_id):
            return error(f"{doctype} '{item_id}' not found.", 404)

        if not is_guest:
            is_enrolled, enroll_msg = _check_enrollment(item_type, item_id, member)
            if is_enrolled:
                return error(enroll_msg, 409)

        if item_type == "batch":
            ok, msg = _validate_batch_access(item_id)
            if not ok:
                return error(msg, 400)

        from lms.lms.utils import get_order_summary
        summary = frappe._dict(get_order_summary(
            doctype=doctype,
            docname=item_id,
            coupon=coupon_code,
            country=country,
        ))

        saved_address = _get_saved_address(member) if not is_guest else {}
        total = flt(summary.get("amount", 0))
        gst   = flt(summary.get("gst_applied", 0))
        total_with_gst = total + gst if gst else total

        return success({
            "item_type": item_type,
            "item_id": item_id,
            "doctype": doctype,
            "title": summary.get("title", ""),
            "currency": summary.get("currency", "INR"),
            "original_amount": flt(summary.get("original_amount", 0)),
            "original_amount_formatted": summary.get("original_amount_formatted", ""),
            "discount_amount": flt(summary.get("discount_amount", 0)),
            "discount_amount_formatted": summary.get("discount_amount_formatted", ""),
            "gst_applied": gst,
            "gst_amount_formatted": summary.get("gst_amount_formatted", ""),
            "amount": total,
            "total_amount": total_with_gst,
            "total_amount_formatted": fmt_money(total_with_gst, 0, summary.get("currency", "INR")),
            "is_free": total_with_gst <= 0,
            "coupon": summary.get("coupon"),
            "saved_address": saved_address,
        }, "Checkout summary fetched successfully")

    except frappe.ValidationError as ve:
        return error(str(ve), 400)
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_checkout_summary")
        return error(str(e), 500)


@frappe.whitelist(allow_guest=True)
def validate_coupon_for_item(item_type, item_id, coupon_code):
    """
    Validate a coupon and return discount preview.
    No payment record is created.
    """
    try:
        item_type = item_type.lower().strip()
        doctype = "LMS Batch" if item_type == "batch" else "LMS Course"

        if not frappe.db.exists(doctype, item_id):
            return error(f"{doctype} '{item_id}' not found.", 404)

        from lms.lms.utils import get_order_summary
        summary = frappe._dict(get_order_summary(
            doctype=doctype,
            docname=item_id,
            coupon=coupon_code,
        ))

        return success({
            "original_amount": flt(summary.get("original_amount", 0)),
            "discount_amount": flt(summary.get("discount_amount", 0)),
            "discount_amount_formatted": summary.get("discount_amount_formatted", ""),
            "amount": flt(summary.get("amount", 0)),
            "currency": summary.get("currency", "INR"),
            "coupon": summary.get("coupon"),
        }, "Coupon validated successfully")

    except frappe.ValidationError as ve:
        return error(str(ve), 400)
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "validate_coupon_for_item")
        return error(str(e), 500)


@frappe.whitelist()
def initiate_payment(item_type, item_id, address, coupon_code=None, country=None):
    """
    Step 1 of payment checkout.

    - Saves billing address (upsert).
    - Computes final amount (coupon + GST).
    - If total <= 0  →  enrolls immediately, returns is_free=true.
    - If total >  0  →  creates Razorpay order + LMS Payment record,
                        returns order details for Razorpay JS SDK.

    address fields: billing_name, address_line1, city, country (required);
                    state, pincode, phone, gstin, pan, source, member_consent (optional).
    """
    try:
        member = frappe.session.user
        if not member or member == "Guest":
            return error("Authentication required", 401)

        item_type = item_type.lower().strip()
        doctype = "LMS Batch" if item_type == "batch" else "LMS Course"

        # parse address
        if isinstance(address, str):
            address_data = frappe._dict(_json.loads(address))
        else:
            address_data = frappe._dict(address)

        # basic validation
        for f in ["billing_name", "city", "country"]:
            if not address_data.get(f):
                return error(f"Billing field '{f}' is required.", 400)

        if not frappe.db.exists(doctype, item_id):
            return error(f"{doctype} '{item_id}' not found.", 404)

        is_enrolled, enroll_msg = _check_enrollment(item_type, item_id, member)
        if is_enrolled:
            return error(enroll_msg, 409)

        if item_type == "batch":
            ok, msg = _validate_batch_access(item_id)
            if not ok:
                return error(msg, 400)

        # pricing
        from lms.lms.utils import get_order_summary, complete_enrollment
        summary = frappe._dict(get_order_summary(
            doctype=doctype,
            docname=item_id,
            coupon=coupon_code,
            country=address_data.get("country"),
        ))

        base_amount     = flt(summary.get("amount", 0))
        original_amount = flt(summary.get("original_amount", 0))
        discount_amount = flt(summary.get("discount_amount", 0))
        gst_applied     = flt(summary.get("gst_applied", 0))
        currency        = summary.get("currency", "INR")
        coupon_name     = summary.get("coupon")
        total_amount    = base_amount + gst_applied if gst_applied else base_amount

        # save address and create LMS Payment
        address_name = _save_billing_address(address_data, member)
        pay_doc = _record_lms_payment(
            member=member,
            address_name=address_name,
            address_data=address_data,
            doctype=doctype,
            docname=item_id,
            amount=base_amount,
            original_amount=original_amount,
            currency=currency,
            discount_amount=discount_amount,
            amount_with_gst=gst_applied,
            coupon=coupon_name,
            coupon_code=coupon_code if coupon_name else None,
            payment_for_certificate=1 if item_type == "certificate" else 0,
        )
        frappe.db.commit()

        # ── FREE path ─────────────────────────────────────────
        if total_amount <= 0:
            frappe.db.set_value("LMS Payment", pay_doc.name, "payment_received", 1)
            frappe.db.commit()
            _execute_enrollment_for_payment(pay_doc.name)
            return success({
                "is_free": True,
                "enrolled": True,
                "payment_name": pay_doc.name,
                "item_type": item_type,
                "item_id": item_id,
            }, "Enrolled successfully (free / full coupon discount)")

        # ── PAID path — create Razorpay order ─────────────────
        rzp_client, api_key, _ = _get_razorpay_client()
        order = _create_razorpay_order(
            amount_inr=total_amount,
            currency=currency,
            receipt=pay_doc.name,
            client=rzp_client,
        )
        frappe.db.set_value("LMS Payment", pay_doc.name, "order_id", order["id"])
        frappe.db.commit()

        return success({
            "is_free": False,
            "payment_name": pay_doc.name,
            "razorpay_order_id": order["id"],
            "razorpay_key_id": api_key,
            "amount": cint(round(total_amount * 100)),  # paise for Razorpay JS
            "amount_display": total_amount,
            "currency": currency,
            "item_type": item_type,
            "item_id": item_id,
            "title": summary.get("title", ""),
            "description": f"Payment for {doctype}: {summary.get('title', item_id)}",
            "prefill": {
                "name":    address_data.get("billing_name", ""),
                "email":   member,
                "contact": address_data.get("phone", ""),
            },
        }, "Payment order created successfully")

    except frappe.ValidationError as ve:
        frappe.db.rollback()
        return error(str(ve), 400)
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "initiate_payment")
        return error(str(e), 500)


@frappe.whitelist()
def verify_payment(payment_name, razorpay_payment_id, razorpay_order_id, razorpay_signature):
    """
    Step 2 of payment checkout — called by frontend after Razorpay modal succeeds.

    - Verifies Razorpay HMAC-SHA256 signature.
    - Marks LMS Payment as received.
    - Enrolls student (course or batch).
    - Updates coupon redemption count.
    """
    try:
        member = frappe.session.user
        if not member or member == "Guest":
            return error("Authentication required", 401)

        if not all([payment_name, razorpay_payment_id, razorpay_order_id, razorpay_signature]):
            return error("Missing required payment verification parameters.", 400)

        pay_doc = frappe.db.get_value(
            "LMS Payment",
            payment_name,
            ["name", "member", "payment_for_document_type", "payment_for_document",
             "payment_received", "order_id", "amount", "amount_with_gst",
             "payment_for_certificate", "coupon"],
            as_dict=True,
        )
        if not pay_doc:
            return error("Payment record not found.", 404)

        if pay_doc.member != member:
            return error("You are not authorised to verify this payment.", 403)

        # idempotent — already processed
        if pay_doc.payment_received:
            _execute_enrollment_for_payment(payment_name)
            return success({
                "already_enrolled": True,
                "enrolled": True,
                "payment_name": payment_name,
                "item_type": "batch" if pay_doc.payment_for_document_type == "LMS Batch" else "course",
                "item_id": pay_doc.payment_for_document,
            }, "Payment was already processed.")

        # verify Razorpay HMAC signature
        _, _, api_secret = _get_razorpay_client()
        body = f"{razorpay_order_id}|{razorpay_payment_id}"
        expected = hmac.new(
            key=api_secret.encode("utf-8"),
            msg=body.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected, razorpay_signature):
            frappe.log_error(
                f"Signature mismatch for payment {payment_name}. "
                f"Expected {expected}, got {razorpay_signature}",
                "Razorpay Signature Mismatch",
            )
            return error("Payment signature verification failed. Contact support.", 400)

        # mark received
        frappe.db.set_value("LMS Payment", payment_name, {
            "payment_received": 1,
            "payment_id": razorpay_payment_id,
            "order_id": razorpay_order_id,
        })
        frappe.db.commit()

        # enroll student safely
        _execute_enrollment_for_payment(payment_name)

        return success({
            "enrolled": True,
            "payment_name": payment_name,
            "razorpay_payment_id": razorpay_payment_id,
            "item_type": "batch" if pay_doc.payment_for_document_type == "LMS Batch" else "course",
            "item_id": pay_doc.payment_for_document,
        }, "Payment verified and enrollment completed successfully.")

    except frappe.ValidationError as ve:
        frappe.db.rollback()
        return error(str(ve), 400)
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "verify_payment")
        return error(str(e), 500)


@frappe.whitelist()
def get_payment_status(payment_name):
    """
    Return the current status of an LMS Payment.
    Useful for polling after a redirect, or webhook-before-callback scenarios.
    """
    try:
        member = frappe.session.user
        if not member or member == "Guest":
            return error("Authentication required", 401)

        pay = frappe.db.get_value(
            "LMS Payment",
            payment_name,
            ["name", "member", "payment_received", "payment_id", "order_id",
             "amount", "amount_with_gst", "currency",
             "payment_for_document_type", "payment_for_document",
             "payment_for_certificate", "creation"],
            as_dict=True,
        )
        if not pay:
            return error("Payment record not found.", 404)
        if pay.member != member:
            return error("Not authorised.", 403)

        is_enrolled = False
        if pay.payment_received:
            if pay.payment_for_document_type == "LMS Course":
                is_enrolled = bool(frappe.db.exists(
                    "LMS Enrollment", {"member": member, "course": pay.payment_for_document}))
            elif pay.payment_for_document_type == "LMS Batch":
                is_enrolled = bool(frappe.db.exists(
                    "LMS Batch Enrollment", {"member": member, "batch": pay.payment_for_document}))

        return success({
            "payment_name":    pay.name,
            "payment_received": bool(pay.payment_received),
            "payment_id":      pay.payment_id,
            "order_id":        pay.order_id,
            "amount":          flt(pay.amount),
            "amount_with_gst": flt(pay.amount_with_gst),
            "currency":        pay.currency,
            "item_type":       "batch" if pay.payment_for_document_type == "LMS Batch" else "course",
            "item_id":         pay.payment_for_document,
            "is_enrolled":     is_enrolled,
            "created_at":      str(pay.creation),
        }, "Payment status fetched.")

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_payment_status")
        return error(str(e), 500)


@frappe.whitelist()
def get_my_payments(limit=20, offset=0):
    """List all LMS Payments for the logged-in student, newest first."""
    try:
        member = frappe.session.user
        if not member or member == "Guest":
            return error("Authentication required", 401)

        limit  = cint(limit)  or 20
        offset = cint(offset) or 0

        payments = frappe.get_all(
            "LMS Payment",
            filters={"member": member},
            fields=[
                "name", "amount", "original_amount", "discount_amount",
                "amount_with_gst", "currency", "payment_received",
                "payment_id", "order_id",
                "payment_for_document_type", "payment_for_document",
                "payment_for_certificate", "coupon_code",
                "billing_name", "creation", "modified",
            ],
            order_by="creation desc",
            limit_page_length=limit,
            limit_start=offset,
        )
        total = frappe.db.count("LMS Payment", {"member": member})

        return success({"payments": payments, "total": total,
                        "limit": limit, "offset": offset},
                       "Payment history fetched.")

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_my_payments")
        return error(str(e), 500)


@frappe.whitelist()
def enroll_in_batch_api(batch):
    """
    Enroll current student in a FREE batch (allow_self_enrollment=1, paid_batch=0).
    For paid batches, use initiate_payment → verify_payment.
    """
    try:
        member = frappe.session.user
        if not member or member == "Guest":
            return error("Authentication required", 401)

        if not frappe.db.exists("LMS Batch", batch):
            return error("Batch not found.", 404)

        batch_doc = frappe.db.get_value(
            "LMS Batch", batch, ["paid_batch", "allow_self_enrollment"], as_dict=True)

        if cint(batch_doc.paid_batch):
            return error("This is a paid batch. Use the payment flow to enroll.", 400)

        if not cint(batch_doc.allow_self_enrollment):
            return error("Self-enrollment is disabled. Contact the administrator.", 400)

        ok, msg = _validate_batch_access(batch)
        if not ok:
            return error(msg, 400)

        is_enrolled, enroll_msg = _check_enrollment("batch", batch, member)
        if is_enrolled:
            return error(enroll_msg, 409)

        from lms.lms.utils import enroll_in_batch
        enroll_in_batch(batch, payment_name=None)
        frappe.db.commit()

        return success({"batch": batch, "member": member}, "Enrolled in batch successfully.")

    except frappe.ValidationError as ve:
        return error(str(ve), 400)
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "enroll_in_batch_api")
        return error(str(e), 500)


@frappe.whitelist()
def get_course_with_enrollment(name):
    """
    Return full course data (with chapters and lessons) plus enrollment
    and pricing metadata for the current user.
    """
    try:
        member = frappe.session.user
        course = frappe.get_doc("LMS Course", name)
        course_data = course.as_dict()

        chapters = frappe.get_all(
            "Course Chapter",
            filters={"course": name},
            fields=["name", "title", "course", "idx", "creation", "modified"],
            order_by="idx asc",
        )
        for chapter in chapters:
            chapter["lessons"] = frappe.get_all(
                "Course Lesson",
                filters={"course": name, "chapter": chapter["name"]},
                fields=["name", "title", "course", "chapter", "idx",
                        "include_in_preview", "creation", "modified"],
                order_by="idx asc",
            )
        course_data["chapters"] = chapters

        course_data["is_paid"]          = bool(cint(course.paid_course))
        course_data["paid_certificate"] = bool(cint(course.paid_certificate))
        course_data["course_price"]     = flt(course.course_price)
        course_data["currency"]         = course.currency
        course_data["amount_usd"]       = flt(course.amount_usd)
        course_data["is_enrolled"]      = False

        if member and member != "Guest":
            enrollment = frappe.db.get_value(
                "LMS Enrollment",
                {"member": member, "course": name},
                ["name", "progress", "purchased_certificate"],
                as_dict=True,
            )
            if enrollment:
                course_data["is_enrolled"] = True
                course_data["enrollment"]  = enrollment
            else:
                # Check if enrolled via a Batch containing this course
                batch_enrollment = frappe.db.sql("""
                    SELECT be.name, be.batch FROM `tabLMS Batch Enrollment` be
                    JOIN `tabBatch Course` bc ON bc.parent = be.batch
                    WHERE be.member = %s AND bc.course = %s
                    LIMIT 1
                """, (member, name), as_dict=True)
                if batch_enrollment:
                    course_data["is_enrolled"] = True
                    course_data["batch_enrollment"] = batch_enrollment[0]

        # Tag each lesson with is_locked status for clean UI gating
        is_enrolled = course_data["is_enrolled"]
        is_paid = course_data["is_paid"]
        for chapter in chapters:
            for lesson in chapter.get("lessons", []):
                lesson["is_locked"] = is_paid and not is_enrolled and not bool(cint(lesson.get("include_in_preview")))

        return success(course_data, "Course fetched successfully.")

    except frappe.DoesNotExistError:
        return error("Course not found.", 404)
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_course_with_enrollment")
        return error(str(e), 500)


@frappe.whitelist()
def get_batch_with_enrollment(name):
    """
    Return full batch data plus enrollment status, seat info, and pricing
    for the current user.
    """
    try:
        member = frappe.session.user
        batch  = frappe.get_doc("LMS Batch", name)
        batch_data = batch.as_dict()

        enrolled_count = frappe.db.count("LMS Batch Enrollment", {"batch": name})
        seat_count     = cint(batch.seat_count)
        seats_left     = max(seat_count - enrolled_count, 0) if seat_count else None

        batch_data["enrolled_count"] = enrolled_count
        batch_data["seats_left"]     = seats_left
        batch_data["is_sold_out"]    = (seat_count > 0 and enrolled_count >= seat_count)
        batch_data["is_paid"]        = bool(cint(batch.paid_batch))
        batch_data["amount"]         = flt(batch.amount)
        batch_data["currency"]       = batch.currency
        batch_data["amount_usd"]     = flt(batch.amount_usd)
        batch_data["is_enrolled"]    = False

        if member and member != "Guest":
            enrollment = frappe.db.get_value(
                "LMS Batch Enrollment",
                {"member": member, "batch": name},
                ["name", "creation"],
                as_dict=True,
            )
            if enrollment:
                batch_data["is_enrolled"] = True
                batch_data["enrollment"]  = enrollment

        return success(batch_data, "Batch fetched successfully.")

    except frappe.DoesNotExistError:
        return error("Batch not found.", 404)
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_batch_with_enrollment")
        return error(str(e), 500)


@frappe.whitelist()
def get_courses_with_enrollment(published=1, limit=20, offset=0):
    """List courses with pricing + enrollment status for the logged-in user."""
    try:
        member = frappe.session.user
        limit  = cint(limit)  or 20
        offset = cint(offset) or 0

        roles = set(frappe.get_roles(member)) if member else set()
        is_privileged = bool(roles.intersection({"Administrator", "System Manager", "Moderator", "Course Creator"}))

        filters = {}
        if not is_privileged:
            # Regular students and guests should only ever see published courses
            filters["published"] = 1
        elif published is not None and str(published).lower() in ("all", "-1"):
            # Privileged users can view all courses if explicitly requested
            pass
        elif published is not None and str(published).strip() != "":
            filters["published"] = cint(published)
        else:
            filters["published"] = 1

        courses = frappe.get_all(
            "LMS Course",
            filters=filters,
            fields=[
                "name", "title", "short_introduction", "description",
                "published", "paid_course", "paid_certificate",
                "course_price", "currency", "amount_usd",
                "enrollments", "lessons", "rating",
                "creation", "modified",
            ],
            limit_page_length=limit,
            limit_start=offset,
            order_by="creation desc",
        )
        total = frappe.db.count("LMS Course", filters)

        enrolled_courses = set()
        if member and member != "Guest":
            enrolled_courses = set(
                frappe.get_all("LMS Enrollment", {"member": member}, pluck="course")
            )

        for c in courses:
            c["is_enrolled"] = c["name"] in enrolled_courses
            c["is_paid"]     = bool(cint(c.get("paid_course")))

        return success({"courses": courses, "total": total,
                        "limit": limit, "offset": offset},
                       "Courses fetched successfully.")

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_courses_with_enrollment")
        return error(str(e), 500)


@frappe.whitelist()
def get_batches_with_enrollment(published=1, limit=20, offset=0):
    """List batches with pricing, seat count, and enrollment status."""
    try:
        member = frappe.session.user
        limit  = cint(limit)  or 20
        offset = cint(offset) or 0

        roles = set(frappe.get_roles(member)) if member else set()
        is_privileged = bool(roles.intersection({"Administrator", "System Manager", "Moderator", "Course Creator"}))

        filters = {}
        if not is_privileged:
            filters["published"] = 1
        elif published is not None and str(published).lower() in ("all", "-1"):
            pass
        elif published is not None and str(published).strip() != "":
            filters["published"] = cint(published)
        else:
            filters["published"] = 1

        batches = frappe.get_all(
            "LMS Batch",
            filters=filters,
            fields=[
                "name", "title", "description", "start_date", "end_date",
                "start_time", "end_time", "seat_count", "published",
                "paid_batch", "amount", "currency", "amount_usd",
                "medium", "allow_self_enrollment",
                "creation", "modified",
            ],
            limit_page_length=limit,
            limit_start=offset,
            order_by="creation desc",
        )
        total = frappe.db.count("LMS Batch", filters)

        enrolled_batches = set()
        if member and member != "Guest":
            enrolled_batches = set(
                frappe.get_all("LMS Batch Enrollment", {"member": member}, pluck="batch")
            )

        for b in batches:
            enrolled_count = frappe.db.count("LMS Batch Enrollment", {"batch": b["name"]})
            seat_count     = cint(b.get("seat_count", 0))
            b["enrolled_count"] = enrolled_count
            b["seats_left"]     = max(seat_count - enrolled_count, 0) if seat_count else None
            b["is_sold_out"]    = (seat_count > 0 and enrolled_count >= seat_count)
            b["is_paid"]        = bool(cint(b.get("paid_batch")))
            b["is_enrolled"]    = b["name"] in enrolled_batches

        return success({"batches": batches, "total": total,
                        "limit": limit, "offset": offset},
                       "Batches fetched successfully.")

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_batches_with_enrollment")
        return error(str(e), 500)


# ============================================================
# RAZORPAY WEBHOOK — Safety net for browser crash / network drop
# ============================================================
# Configure in Razorpay Dashboard:
#   URL  → https://devlms.stridenex.ai/api/method/lms.lms.stride_lms.razorpay_webhook
#   Events → payment.captured
#   Webhook Secret → use the same api_secret (rzp_test_... key secret)
# ============================================================

@frappe.whitelist(allow_guest=True)
def razorpay_webhook():
    """
    Razorpay calls this server-to-server whenever a payment is captured.

    This is the safety net for when the student's browser crashes or
    their internet drops after payment — the normal verify_payment flow
    in the browser would not have fired, leaving the student paid but
    not enrolled. This webhook completes the enrollment.

    Security: Razorpay signs every webhook request with HMAC-SHA256.
    We verify the signature before doing anything.
    """
    try:
        # ── read raw body and signature header ────────────────
        raw_body = frappe.request.get_data(as_text=True)
        signature = frappe.request.headers.get("X-Razorpay-Signature", "")

        if not raw_body or not signature:
            frappe.local.response.http_status_code = 400
            return {"status": "error", "message": "Missing body or signature"}

        # ── verify webhook signature ──────────────────────────
        rzp = frappe.get_doc("Razorpay Settings")
        webhook_secret = rzp.get_password(fieldname="api_secret", raise_exception=False)

        expected = hmac.new(
            key=webhook_secret.encode("utf-8"),
            msg=raw_body.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected, signature):
            frappe.log_error(
                f"Webhook signature mismatch.\nExpected: {expected}\nGot: {signature}",
                "Razorpay Webhook Signature Mismatch",
            )
            frappe.local.response.http_status_code = 400
            return {"status": "error", "message": "Invalid webhook signature"}

        # ── parse event payload ───────────────────────────────
        payload = _json.loads(raw_body)
        event = payload.get("event", "")

        # We only care about payment.captured
        if event not in ("payment.captured", "payment.authorized"):
            return {"status": "ok", "message": f"Event '{event}' ignored"}

        payment_entity = (
            payload.get("payload", {})
                   .get("payment", {})
                   .get("entity", {})
        )
        razorpay_payment_id = payment_entity.get("id")
        razorpay_order_id   = payment_entity.get("order_id")

        if not razorpay_order_id:
            return {"status": "ok", "message": "No order_id in payload"}

        # ── find our LMS Payment by order_id ─────────────────
        payment_name = frappe.db.get_value(
            "LMS Payment", {"order_id": razorpay_order_id}, "name"
        )
        if not payment_name:
            # Could be a payment not initiated through our system — ignore
            frappe.log_error(
                f"Webhook: no LMS Payment found for order_id={razorpay_order_id}",
                "Razorpay Webhook Unknown Order",
            )
            return {"status": "ok", "message": "Order not found in LMS — ignored"}

        pay_doc = frappe.db.get_value(
            "LMS Payment",
            payment_name,
            ["name", "payment_received", "payment_for_document_type",
             "payment_for_document", "member"],
            as_dict=True,
        )

        # Already processed (normal verify_payment already ran) — idempotent
        if pay_doc.payment_received:
            _execute_enrollment_for_payment(payment_name)
            return {"status": "ok", "message": "Already processed"}

        # ── mark payment received ─────────────────────────────
        frappe.db.set_value("LMS Payment", payment_name, {
            "payment_received": 1,
            "payment_id": razorpay_payment_id,
        })
        frappe.db.commit()

        # ── enroll student safely ─────────────────────────────
        _execute_enrollment_for_payment(payment_name)

        frappe.log_error(
            f"Webhook enrollment completed: payment={payment_name}, "
            f"member={pay_doc.member}, item={pay_doc.payment_for_document}",
            "Razorpay Webhook Enrollment",
        )
        return {"status": "ok", "message": "Enrollment completed via webhook"}

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "razorpay_webhook")
        frappe.local.response.http_status_code = 500
        return {"status": "error", "message": str(e)}


# ============================================================
# STUDENT DASHBOARD API
# ============================================================

@frappe.whitelist(allow_guest=True)
def get_student_dashboard(member=None):
    """
    Comprehensive dashboard data for the logged-in student.
    Returns:
      - courses: Enrolled courses with progress, lesson stats, and instructors
      - batches: Enrolled cohorts with schedule, timings, and included courses
      - programs: Enrolled learning paths with progress
      - stats: Aggregated totals
    """
    try:
        current_user = frappe.session.user
        target_member = member or current_user
        if not target_member or target_member == "Guest":
            return error("Authentication required to access student dashboard.", 401)

        # ── 1. Enrolled Courses ──
        enrollments = frappe.get_all(
            "LMS Enrollment",
            filters={"member": target_member},
            fields=["name", "course", "progress", "current_lesson", "enrollment_from_batch", "payment", "creation"],
            order_by="creation desc"
        )

        course_names = [e.course for e in enrollments if e.course]
        courses_meta = {}
        if course_names:
            c_records = frappe.get_all(
                "LMS Course",
                filters={"name": ["in", course_names]},
                fields=["name", "title", "image", "short_introduction", "description", "category", "lessons", "paid_course", "course_price", "currency"]
            )
            for c in c_records:
                courses_meta[c.name] = c

        courses_list = []
        completed_count = 0
        for e in enrollments:
            c_meta = courses_meta.get(e.course, {})
            progress_val = flt(e.progress or 0)
            if progress_val >= 100:
                completed_count += 1

            instructors = get_instructors("LMS Course", e.course) if e.course else []
            total_lessons = cint(c_meta.get("lessons") or 0) or frappe.db.count("Course Lesson", {"course": e.course})
            completed_lessons = 0
            if total_lessons > 0:
                completed_lessons = int(round((progress_val / 100.0) * total_lessons))

            courses_list.append({
                "enrollment_id": e.name,
                "course": e.course,
                "course_title": c_meta.get("title") or e.course,
                "title": c_meta.get("title") or e.course,
                "image": c_meta.get("image"),
                "short_introduction": c_meta.get("short_introduction") or c_meta.get("description"),
                "category": c_meta.get("category"),
                "progress": progress_val,
                "completed_lessons": completed_lessons,
                "total_lessons": total_lessons,
                "current_lesson": e.current_lesson,
                "enrollment_from_batch": e.enrollment_from_batch,
                "instructors": instructors,
                "enrolled_on": e.creation,
                "is_enrolled": True,
                "is_paid": bool(c_meta.get("paid_course")),
            })

        # ── 2. Enrolled Batches ──
        batch_enrollments = frappe.get_all(
            "LMS Batch Enrollment",
            filters={"member": target_member},
            fields=["name", "batch", "payment", "creation"],
            order_by="creation desc"
        )
        batch_names = [b.batch for b in batch_enrollments if b.batch]
        batches_meta = {}
        if batch_names:
            b_records = frappe.get_all(
                "LMS Batch",
                filters={"name": ["in", batch_names]},
                fields=["name", "title", "description", "start_date", "end_date", "start_time", "end_time", "medium", "seat_count", "paid_batch", "amount", "currency"]
            )
            for b in b_records:
                batches_meta[b.name] = b

        batches_list = []
        for be in batch_enrollments:
            b_meta = batches_meta.get(be.batch, {})
            courses_in_batch = frappe.get_all("Batch Course", filters={"parent": be.batch}, pluck="course")
            instructors = get_instructors("LMS Batch", be.batch) if be.batch else []

            batches_list.append({
                "enrollment_id": be.name,
                "batch": be.batch,
                "title": b_meta.get("title") or be.batch,
                "description": b_meta.get("description"),
                "start_date": b_meta.get("start_date"),
                "end_date": b_meta.get("end_date"),
                "start_time": b_meta.get("start_time"),
                "end_time": b_meta.get("end_time"),
                "medium": b_meta.get("medium"),
                "courses": courses_in_batch,
                "courses_count": len(courses_in_batch),
                "instructors": instructors,
                "enrolled_on": be.creation,
                "is_enrolled": True,
            })

        # ── 3. Enrolled Programs ──
        prog_members = frappe.get_all(
            "LMS Program Member",
            filters={"member": target_member},
            fields=["name", "parent", "progress", "creation"]
        )
        programs_list = []
        for pm in prog_members:
            prog_meta = frappe.db.get_value("LMS Program", pm.parent, ["title", "published"], as_dict=True) or {}
            prog_courses = frappe.get_all("LMS Program Course", filters={"parent": pm.parent}, pluck="course")
            programs_list.append({
                "membership_id": pm.name,
                "program": pm.parent,
                "title": prog_meta.get("title") or pm.parent,
                "progress": flt(pm.progress or 0),
                "courses_count": len(prog_courses),
                "enrolled_on": pm.creation,
                "is_enrolled": True,
            })

        # ── 4. Certificates ──
        certificates_count = frappe.db.count("LMS Certificate", {"member": target_member})

        return success({
            "courses": courses_list,
            "batches": batches_list,
            "programs": programs_list,
            "stats": {
                "enrolled_courses": len(courses_list),
                "completed_courses": completed_count,
                "enrolled_batches": len(batches_list),
                "enrolled_programs": len(programs_list),
                "certificates_earned": certificates_count,
            }
        }, "Student dashboard fetched successfully.")

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_student_dashboard")
        return error(str(e), 500)


# ============================================================
# INSTRUCTOR / CREATOR SALES DASHBOARD API
# ============================================================

@frappe.whitelist(allow_guest=True)
def get_instructor_dashboard(instructor=None):
    """
    Sales, enrollment analytics, and course management dashboard for Instructors / Creators.
    Returns:
      - stats: Total Revenue, Unique Students, Total Courses, Total Cohorts
      - courses: Detailed list of courses with per-course student counts & revenue
      - batches: Cohort batches with seat counts and enrollment stats
      - recent_sales: Activity stream of recent student purchases / enrollments
      - is_instructor: Boolean indicator of instructor status
    """
    try:
        current_user = frappe.session.user
        target_instructor = instructor or current_user
        if not target_instructor or target_instructor == "Guest":
            return error("Authentication required to access instructor dashboard.", 401)

        roles = set(frappe.get_roles(target_instructor))
        is_admin = bool(roles.intersection({"Administrator", "System Manager"}))
        has_instructor_role = is_admin or bool(roles.intersection({"Instructor", "Course Creator", "Moderator"}))

        # Check if user owns or teaches any courses / batches
        course_rows = frappe.db.sql("""
            SELECT DISTINCT c.name
            FROM `tabLMS Course` c
            LEFT JOIN `tabCourse Instructor` ci ON ci.parent = c.name AND ci.parenttype = 'LMS Course'
            WHERE c.owner = %s OR ci.instructor = %s
            ORDER BY c.creation DESC
        """, (target_instructor, target_instructor), as_dict=True)
        course_names = [r.name for r in course_rows]

        batch_rows = frappe.db.sql("""
            SELECT DISTINCT b.name
            FROM `tabLMS Batch` b
            LEFT JOIN `tabCourse Instructor` ci ON ci.parent = b.name AND ci.parenttype = 'LMS Batch'
            WHERE b.owner = %s OR ci.instructor = %s
            ORDER BY b.creation DESC
        """, (target_instructor, target_instructor), as_dict=True)
        batch_names = [r.name for r in batch_rows]

        # If admin and has no specific courses assigned, load all courses so admin has full visibility
        if is_admin and not course_names:
            course_names = frappe.get_all("LMS Course", pluck="name", order_by="creation desc")
        if is_admin and not batch_names:
            batch_names = frappe.get_all("LMS Batch", pluck="name", order_by="creation desc")

        is_instructor = has_instructor_role or len(course_names) > 0 or len(batch_names) > 0
        if not is_instructor:
            return success({
                "is_instructor": False,
                "message": "User is not registered as an Instructor or Course Creator.",
                "stats": {
                    "total_revenue": 0,
                    "total_students": 0,
                    "total_courses": 0,
                    "published_courses": 0,
                    "draft_courses": 0,
                    "total_batches": 0,
                },
                "courses": [],
                "batches": [],
                "recent_sales": []
            }, "User is not an instructor.")

        unique_students = set()
        courses_list = []
        total_course_revenue = 0

        for c_name in course_names:
            c_doc = frappe.db.get_value(
                "LMS Course",
                c_name,
                [
                    "name", "title", "image", "published", "paid_course",
                    "course_price", "currency", "lessons", "rating",
                    "category", "short_introduction", "description", "creation"
                ],
                as_dict=True
            )
            if not c_doc:
                continue

            enrolled_members = frappe.get_all("LMS Enrollment", filters={"course": c_name}, pluck="member")
            for m in enrolled_members:
                unique_students.add(m)

            payments = frappe.get_all(
                "LMS Payment",
                filters={"payment_for_document": c_name, "payment_received": 1},
                fields=["amount", "amount_with_gst"]
            )
            course_rev = sum(flt(p.amount_with_gst or p.amount or 0) for p in payments)
            total_course_revenue += course_rev

            lessons_count = cint(c_doc.lessons or 0) or frappe.db.count("Course Lesson", {"course": c_name})

            courses_list.append({
                "name": c_doc.name,
                "title": c_doc.title or c_doc.name,
                "image": c_doc.image,
                "published": bool(c_doc.published),
                "paid_course": bool(c_doc.paid_course),
                "price": flt(c_doc.course_price or 0),
                "currency": c_doc.currency or "INR",
                "category": c_doc.category,
                "short_introduction": c_doc.short_introduction or c_doc.description,
                "enrollments_count": len(enrolled_members),
                "revenue": course_rev,
                "lessons_count": lessons_count,
                "rating": flt(c_doc.rating or 0),
                "created_at": c_doc.creation,
            })

        batches_list = []
        total_batch_revenue = 0

        for b_name in batch_names:
            b_doc = frappe.db.get_value(
                "LMS Batch",
                b_name,
                [
                    "name", "title", "description", "start_date", "end_date",
                    "start_time", "end_time", "seat_count", "published",
                    "paid_batch", "amount", "currency", "medium", "creation"
                ],
                as_dict=True
            )
            if not b_doc:
                continue

            enrolled_members = frappe.get_all("LMS Batch Enrollment", filters={"batch": b_name}, pluck="member")
            for m in enrolled_members:
                unique_students.add(m)

            b_payments = frappe.get_all(
                "LMS Payment",
                filters={"payment_for_document": b_name, "payment_received": 1},
                fields=["amount", "amount_with_gst"]
            )
            batch_rev = sum(flt(p.amount_with_gst or p.amount or 0) for p in b_payments)
            total_batch_revenue += batch_rev

            seat_count = cint(b_doc.seat_count or 0)
            enrolled_count = len(enrolled_members)
            seats_left = max(seat_count - enrolled_count, 0) if seat_count else None

            batches_list.append({
                "name": b_doc.name,
                "title": b_doc.title or b_doc.name,
                "description": b_doc.description,
                "start_date": b_doc.start_date,
                "end_date": b_doc.end_date,
                "start_time": b_doc.start_time,
                "end_time": b_doc.end_time,
                "medium": b_doc.medium,
                "seat_count": seat_count,
                "enrolled_count": enrolled_count,
                "seats_left": seats_left,
                "is_sold_out": bool(seat_count and enrolled_count >= seat_count),
                "paid_batch": bool(b_doc.paid_batch),
                "amount": flt(b_doc.amount or 0),
                "currency": b_doc.currency or "INR",
                "revenue": batch_rev,
                "published": bool(b_doc.published),
                "created_at": b_doc.creation,
            })

        # Recent transactions / sales stream
        recent_sales = []
        all_item_names = set(course_names + batch_names)
        if all_item_names:
            recent_payments = frappe.get_all(
                "LMS Payment",
                filters={"payment_for_document": ["in", list(all_item_names)], "payment_received": 1},
                fields=[
                    "name", "member", "billing_name", "amount",
                    "amount_with_gst", "currency", "payment_for_document_type",
                    "payment_for_document", "creation", "payment_id"
                ],
                order_by="creation desc",
                limit=15
            )
            for p in recent_payments:
                progress_val = None
                if p.payment_for_document_type == "LMS Course":
                    progress_val = frappe.db.get_value("LMS Enrollment", {"member": p.member, "course": p.payment_for_document}, "progress")

                recent_sales.append({
                    "payment_name": p.name,
                    "payment_id": p.payment_id,
                    "member": p.member,
                    "student_name": p.billing_name or (p.member.split("@")[0] if p.member else "Student"),
                    "item_type": "Batch" if p.payment_for_document_type == "LMS Batch" else "Course",
                    "item_name": p.payment_for_document,
                    "amount": flt(p.amount_with_gst or p.amount or 0),
                    "currency": p.currency or "INR",
                    "created_at": p.creation,
                    "progress": flt(progress_val or 0) if progress_val is not None else None,
                })

        total_rev = total_course_revenue + total_batch_revenue

        return success({
            "is_instructor": True,
            "instructor": target_instructor,
            "stats": {
                "total_revenue": total_rev,
                "total_students": len(unique_students),
                "total_courses": len(courses_list),
                "published_courses": sum(1 for c in courses_list if c["published"]),
                "draft_courses": sum(1 for c in courses_list if not c["published"]),
                "total_batches": len(batches_list),
            },
            "courses": courses_list,
            "batches": batches_list,
            "recent_sales": recent_sales
        }, "Instructor dashboard fetched successfully.")

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_instructor_dashboard")
        return error(str(e), 500)

# ═══════════════════════════════════════════════════════════════════════════════
#  INSTRUCTOR BILLING SYSTEM
#  Modelled after the Stridenex Mentor Payout Sheet logic.
#
#  Complete Calculation Formula per instructor per period:
#   gross_sales         = SUM(LMS Payment.amount) WHERE payment_received=1
#                         for all their course + batch payments in the period
#   commission_rate     = Tiered lookup from LMS Instructor Billing Settings
#   platform_commission = gross_sales x commission_rate%
#   gst_on_commission   = platform_commission x 18%  (if apply_gst_on_commission=1)
#   refunds             = SUM of reversed payments (currently 0; future field)
#   net_earnings        = gross_sales - platform_commission - gst_on_commission - refunds
#   tds_rate            = settings.tds_rate  (if net_earnings >= tds_threshold, else 0)
#   tds_amount          = net_earnings x tds_rate%
#   net_payout          = net_earnings - tds_amount
#
#  Admin Flow:
#   1. generate_instructor_payout_sheet(start_date, end_date)
#      → Creates / refreshes LMS Instructor Payout Sheet document
#   2. Admin reviews, checks "Release Payout" per instructor row
#   3. approve_instructor_payout(sheet_name)
#      → Marks approved rows, creates individual LMS Instructor Billing records
#   4. mark_payout_paid(billing_name, payment_reference, ...)
#      → Updates billing status to Paid after actual bank transfer
#
#  Instructor (Self-Service) Flow:
#   - get_instructor_billing_dashboard() → Earnings history, TDS summary, pending payout
#   - preview_instructor_billing()       → Live preview of current month's estimate
# ═══════════════════════════════════════════════════════════════════════════════


def _require_admin():
    """Ensure session user has System Manager, Administrator, or LMS Admin role."""
    user = getattr(frappe.session, "user", None)
    if not user or user == "Administrator":
        return
    roles = frappe.get_roles(user)
    if not any(r in roles for r in ["Administrator", "System Manager", "LMS Admin"]):
        frappe.throw("Access denied. Admin or System Manager role required.", frappe.PermissionError)


def _get_billing_settings():
    """Load LMS Instructor Billing Settings with safe defaults."""
    try:
        s = frappe.get_single("LMS Instructor Billing Settings")
    except Exception:
        s = frappe._dict()

    tds_threshold  = float(getattr(s, "tds_threshold", 0) or 30000.0)
    tds_rate       = float(getattr(s, "tds_rate", 0) or 10.0)
    default_comm   = float(getattr(s, "default_commission_rate", 0) or 20.0)
    apply_gst_comm = int(getattr(s, "apply_gst_on_commission", 1))
    min_payout     = float(getattr(s, "min_payout_threshold", 0) or 500.0)
    cycle          = getattr(s, "billing_cycle", None) or "Monthly"

    tiers = []
    for tier in (s.get("commission_tiers") or []):
        tiers.append({
            "threshold": float(tier.gross_threshold or 0),
            "rate": float(tier.commission_rate or 0)
        })
    if not tiers:
        tiers = [
            {"threshold": 0.0,      "rate": 20.0},
            {"threshold": 50000.0,  "rate": 15.0},
            {"threshold": 100000.0, "rate": 10.0},
        ]
    tiers = sorted(tiers, key=lambda x: x["threshold"])

    return frappe._dict(
        tds_threshold=tds_threshold,
        tds_rate=tds_rate,
        default_commission_rate=default_comm,
        apply_gst_on_commission=apply_gst_comm,
        min_payout_threshold=min_payout,
        billing_cycle=cycle,
        commission_tiers=tiers
    )


def _get_commission_rate(gross_sales, tiers, default_rate):
    """Return applicable commission rate (%) from tiers based on gross_sales."""
    rate = default_rate
    for tier in tiers:
        if gross_sales >= tier["threshold"]:
            rate = tier["rate"]
    return rate


def _get_instructor_courses_and_batches(instructor_email):
    """Return (course_names_list, batch_names_list) for an instructor."""
    ci_rows = frappe.db.sql(
        "SELECT DISTINCT parent FROM `tabCourse Instructor` WHERE instructor = %(e)s",
        {"e": instructor_email}, as_dict=True
    )
    owner_courses = frappe.db.sql(
        "SELECT DISTINCT name FROM `tabLMS Course` WHERE owner = %(e)s",
        {"e": instructor_email}, as_dict=True
    )
    course_names = list({r.parent for r in ci_rows} | {r.name for r in owner_courses})

    batch_rows = frappe.db.sql(
        """SELECT DISTINCT b.name
           FROM `tabLMS Batch` b
           LEFT JOIN `tabBatch Course` bc ON bc.parent = b.name
           WHERE b.owner = %(e)s OR (%(c)s AND bc.course IN %(courses)s)""",
        {"e": instructor_email, "courses": course_names or ["__none__"],
         "c": 1 if course_names else 0},
        as_dict=True
    )
    batch_names = [r.name for r in batch_rows]
    return course_names, batch_names


def _calculate_instructor_financials(instructor_email, start_date, end_date, settings):
    """
    Core calculation: returns full financial breakdown dict for one instructor.
    Returns None if instructor has no courses/batches.
    """
    course_names, batch_names = _get_instructor_courses_and_batches(instructor_email)
    if not course_names and not batch_names:
        return None

    # Course payments
    cp = frappe.db.sql(
        """SELECT COALESCE(SUM(p.amount), 0) as total, COUNT(*) as cnt
           FROM `tabLMS Payment` p
           WHERE p.payment_received = 1
             AND p.payment_for_document_type = 'LMS Course'
             AND p.payment_for_document IN %(courses)s
             AND DATE(p.creation) BETWEEN %(s)s AND %(e)s""",
        {"courses": course_names or ["__none__"], "s": start_date, "e": end_date},
        as_dict=True
    )
    course_gross = float(cp[0].total) if cp else 0.0
    course_cnt   = int(cp[0].cnt) if cp else 0

    # Batch payments
    bp = frappe.db.sql(
        """SELECT COALESCE(SUM(p.amount), 0) as total, COUNT(*) as cnt
           FROM `tabLMS Payment` p
           WHERE p.payment_received = 1
             AND p.payment_for_document_type = 'LMS Batch'
             AND p.payment_for_document IN %(batches)s
             AND DATE(p.creation) BETWEEN %(s)s AND %(e)s""",
        {"batches": batch_names or ["__none__"], "s": start_date, "e": end_date},
        as_dict=True
    )
    batch_gross = float(bp[0].total) if bp else 0.0
    batch_cnt   = int(bp[0].cnt) if bp else 0

    gross_sales = course_gross + batch_gross
    total_txn   = course_cnt + batch_cnt

    comm_rate           = _get_commission_rate(gross_sales, settings.commission_tiers, settings.default_commission_rate)
    platform_commission = round((comm_rate / 100.0) * gross_sales, 2)
    gst_on_commission   = round(platform_commission * 0.18, 2) if settings.apply_gst_on_commission else 0.0
    refunds             = 0.0
    net_earnings        = round(gross_sales - platform_commission - gst_on_commission - refunds, 2)

    tds_rate   = 0.0
    tds_amount = 0.0
    if net_earnings >= settings.tds_threshold:
        tds_rate   = settings.tds_rate
        tds_amount = round((tds_rate / 100.0) * net_earnings, 2)

    net_payout = round(net_earnings - tds_amount, 2)

    instructor_name = frappe.db.get_value("User", instructor_email, "full_name") or instructor_email

    return {
        "instructor": instructor_email,
        "instructor_name": instructor_name,
        "total_sales": total_txn,
        "gross_sales": gross_sales,
        "course_gross": course_gross,
        "batch_gross": batch_gross,
        "platform_commission_rate": comm_rate,
        "platform_commission": platform_commission,
        "gst_on_commission": gst_on_commission,
        "refunds": refunds,
        "net_earnings": net_earnings,
        "tds_rate": tds_rate,
        "tds_amount": tds_amount,
        "net_payout": net_payout,
        "status": "Draft",
        "released": 0
    }


@frappe.whitelist()
def generate_instructor_payout_sheet(start_date, end_date, billing_cycle=None, instructor=None):
    """
    Admin: Calculate & generate (or refresh) an LMS Instructor Payout Sheet.

    If a Draft sheet already exists for the same period, it is refreshed.
    Released checkbox state is preserved across refreshes.

    Args:
        start_date    - Period start (YYYY-MM-DD)
        end_date      - Period end   (YYYY-MM-DD)
        billing_cycle - Monthly / Weekly / Fortnightly / Quarterly
        instructor    - Filter to a single instructor email (optional)

    Returns JSON with sheet_name, instructor_rows[], summary stats.
    """
    _require_admin()
    settings = _get_billing_settings()
    cycle    = billing_cycle or settings.billing_cycle

    # Discover instructors
    if instructor:
        instructor_emails = [instructor]
    else:
        role_users = frappe.db.sql(
            """SELECT DISTINCT u.name FROM `tabUser` u
               JOIN `tabHas Role` hr ON hr.parent = u.name
               WHERE hr.role IN ('Instructor', 'Course Creator', 'Moderator')
                 AND u.enabled = 1 AND u.name NOT IN ('Administrator','Guest')""",
            as_dict=True
        )
        instructor_emails = [u.name for u in role_users]
        content_owners = frappe.db.sql(
            """SELECT DISTINCT owner FROM `tabLMS Course` WHERE owner NOT IN ('Administrator','Guest')
               UNION
               SELECT DISTINCT owner FROM `tabLMS Batch` WHERE owner NOT IN ('Administrator','Guest')""",
            as_dict=True
        )
        for r in content_owners:
            if r.owner and r.owner not in instructor_emails:
                instructor_emails.append(r.owner)

    # Existing draft sheet for this period?
    existing = frappe.db.get_value(
        "LMS Instructor Payout Sheet",
        {"start_date": start_date, "end_date": end_date, "billing_cycle": cycle, "docstatus": 0},
        "name"
    )
    if existing:
        sheet_doc = frappe.get_doc("LMS Instructor Payout Sheet", existing)
        released_map = {r.instructor: bool(r.released) for r in sheet_doc.instructor_rows}
    else:
        sheet_doc = frappe.get_doc({
            "doctype": "LMS Instructor Payout Sheet",
            "billing_cycle": cycle,
            "start_date": start_date,
            "end_date": end_date
        })
        released_map = {}

    rows = []
    stats = {"total_gross": 0.0, "total_commission": 0.0, "total_tds": 0.0,
             "total_net_payout": 0.0, "instructor_count": 0, "transaction_count": 0}

    for email in instructor_emails:
        data = _calculate_instructor_financials(email, start_date, end_date, settings)
        if data is None:
            continue
        data["released"] = 1 if released_map.get(email, False) else 0
        rows.append(data)
        stats["total_gross"]        += data["gross_sales"]
        stats["total_commission"]   += data["platform_commission"] + data["gst_on_commission"]
        stats["total_tds"]          += data["tds_amount"]
        stats["total_net_payout"]   += data["net_payout"]
        stats["instructor_count"]   += 1
        stats["transaction_count"]  += data["total_sales"]

    sheet_doc.set("instructor_rows", [])
    for d in rows:
        sheet_doc.append("instructor_rows", {
            "released": d["released"], "instructor": d["instructor"],
            "instructor_name": d["instructor_name"], "total_sales": d["total_sales"],
            "gross_sales": d["gross_sales"], "platform_commission_rate": d["platform_commission_rate"],
            "platform_commission": d["platform_commission"], "gst_on_commission": d["gst_on_commission"],
            "refunds": d["refunds"], "net_earnings": d["net_earnings"],
            "tds_rate": d["tds_rate"], "tds_amount": d["tds_amount"],
            "net_payout": d["net_payout"], "status": "Draft"
        })

    if existing:
        sheet_doc.save(ignore_permissions=True)
    else:
        sheet_doc.insert(ignore_permissions=True)
    frappe.db.commit()

    return success({
        "sheet_name": sheet_doc.name,
        "billing_cycle": cycle,
        "start_date": start_date,
        "end_date": end_date,
        "summary": stats,
        "settings": {
            "tds_threshold": settings.tds_threshold,
            "tds_rate": settings.tds_rate,
            "default_commission_rate": settings.default_commission_rate,
            "apply_gst_on_commission": bool(settings.apply_gst_on_commission),
            "commission_tiers": settings.commission_tiers,
            "min_payout_threshold": settings.min_payout_threshold
        },
        "instructor_rows": rows
    }, f"Payout sheet '{sheet_doc.name}' generated for {start_date} to {end_date}.")


@frappe.whitelist()
def approve_instructor_payout(sheet_name, instructor_list=None):
    """
    Admin: Approve and release payouts for instructors in a payout sheet.
    Creates individual LMS Instructor Billing records for each approved instructor.

    Args:
        sheet_name      - Name of the LMS Instructor Payout Sheet
        instructor_list - JSON array of instructor emails (if None: approves all released=1 rows)

    Returns list of created billing document names.
    """
    _require_admin()
    sheet_doc = frappe.get_doc("LMS Instructor Payout Sheet", sheet_name)
    if sheet_doc.docstatus != 0:
        return error(f"Payout sheet '{sheet_name}' is already submitted or cancelled.")

    if instructor_list and isinstance(instructor_list, str):
        import json as _j
        instructor_list = _j.loads(instructor_list)

    settings = _get_billing_settings()
    created  = []

    for row in sheet_doc.instructor_rows:
        if instructor_list and row.instructor not in instructor_list:
            continue
        if instructor_list is None and not row.released:
            continue
        if float(row.net_payout or 0) < settings.min_payout_threshold:
            frappe.logger().info(
                f"Skipping {row.instructor}: net_payout {row.net_payout} < min {settings.min_payout_threshold}"
            )
            continue

        row.released = 1
        row.status   = "Approved"

        existing_bill = frappe.db.get_value(
            "LMS Instructor Billing",
            {"payout_sheet": sheet_name, "instructor": row.instructor}, "name"
        )
        if existing_bill:
            created.append(existing_bill)
            continue

        bill = frappe.get_doc({
            "doctype": "LMS Instructor Billing",
            "instructor": row.instructor, "instructor_name": row.instructor_name,
            "payout_sheet": sheet_name, "billing_cycle": sheet_doc.billing_cycle,
            "start_date": sheet_doc.start_date, "end_date": sheet_doc.end_date,
            "gross_sales": row.gross_sales,
            "platform_commission_rate": row.platform_commission_rate,
            "platform_commission": row.platform_commission,
            "gst_on_commission": row.gst_on_commission,
            "refunds": row.refunds, "net_earnings": row.net_earnings,
            "tds_rate": row.tds_rate, "tds_amount": row.tds_amount,
            "net_payout": row.net_payout, "status": "Approved"
        })
        bill.insert(ignore_permissions=True)
        created.append(bill.name)

    sheet_doc.status = "Approved"
    sheet_doc.save(ignore_permissions=True)
    frappe.db.commit()

    return success({
        "sheet_name": sheet_name,
        "approved_count": len(created),
        "billing_docs": created
    }, f"Approved {len(created)} instructor payouts.")


@frappe.whitelist()
def mark_payout_paid(billing_name, payment_reference, payment_mode="Bank Transfer", paid_on=None):
    """
    Admin: Mark an LMS Instructor Billing record as Paid after actual bank transfer.

    Args:
        billing_name      - Name of LMS Instructor Billing document
        payment_reference - Bank UTR number or RazorpayX transfer ID
        payment_mode      - Bank Transfer / RazorpayX / UPI / Manual
        paid_on           - Date of payment (defaults to today)
    """
    _require_admin()
    doc = frappe.get_doc("LMS Instructor Billing", billing_name)
    if doc.status == "Paid":
        return error(f"Billing '{billing_name}' is already marked Paid.")

    from frappe.utils import today
    doc.status            = "Paid"
    doc.payment_reference = payment_reference
    doc.payment_mode      = payment_mode
    doc.paid_on           = paid_on or today()
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return success({
        "billing_name": billing_name,
        "instructor": doc.instructor,
        "net_payout": float(doc.net_payout or 0),
        "status": "Paid",
        "paid_on": str(doc.paid_on),
        "payment_reference": doc.payment_reference
    }, f"Payout '{billing_name}' marked as Paid.")


@frappe.whitelist(allow_guest=True)
def get_instructor_billing_dashboard(instructor=None):
    """
    Instructor self-service: Returns billing/earnings history for the logged-in instructor.

    Returns:
        - lifetime_stats: gross, net, TDS, commission, pending, paid
        - billing_history: list of all LMS Instructor Billing records
        - recent_transactions: last 20 individual student payments feeding their earnings
        - settings: current platform billing settings for UI display
    """
    user = frappe.session.user
    if user == "Guest":
        return error("Authentication required.", 401)

    target = instructor if instructor else user
    if target != user:
        roles = frappe.get_roles(user)
        if not any(r in roles for r in ["Administrator", "System Manager", "Moderator"]):
            return error("Permission denied.", 403)

    billings = frappe.db.sql(
        """SELECT name, payout_sheet, billing_cycle, start_date, end_date,
                  gross_sales, platform_commission_rate, platform_commission,
                  gst_on_commission, refunds, net_earnings,
                  tds_rate, tds_amount, net_payout,
                  status, paid_on, payment_reference, payment_mode, creation
           FROM `tabLMS Instructor Billing`
           WHERE instructor = %(i)s
           ORDER BY creation DESC""",
        {"i": target}, as_dict=True
    )

    lifetime_gross = sum(float(b.gross_sales or 0) for b in billings)
    lifetime_net   = sum(float(b.net_payout or 0) for b in billings)
    lifetime_tds   = sum(float(b.tds_amount or 0) for b in billings)
    lifetime_comm  = sum(float(b.platform_commission or 0) + float(b.gst_on_commission or 0) for b in billings)
    pending        = sum(float(b.net_payout or 0) for b in billings if b.status in ("Approved", "Draft"))
    paid_out       = sum(float(b.net_payout or 0) for b in billings if b.status == "Paid")

    course_names, batch_names = _get_instructor_courses_and_batches(target)
    recent_txn = frappe.db.sql(
        """SELECT p.name, p.member, p.billing_name as student_name,
                  p.payment_for_document_type as item_type,
                  p.payment_for_document as item_name,
                  p.amount, p.currency, p.creation, p.payment_id
           FROM `tabLMS Payment` p
           WHERE p.payment_received = 1
             AND ((p.payment_for_document_type = 'LMS Course' AND p.payment_for_document IN %(c)s)
               OR (p.payment_for_document_type = 'LMS Batch'  AND p.payment_for_document IN %(b)s))
           ORDER BY p.creation DESC
           LIMIT 20""",
        {"c": course_names or ["__none__"], "b": batch_names or ["__none__"]},
        as_dict=True
    )

    settings = _get_billing_settings()

    return success({
        "instructor": target,
        "instructor_name": frappe.db.get_value("User", target, "full_name") or target,
        "lifetime_stats": {
            "lifetime_gross_sales": lifetime_gross,
            "lifetime_net_earnings": lifetime_net,
            "lifetime_tds_deducted": lifetime_tds,
            "lifetime_platform_commission": lifetime_comm,
            "pending_payout": pending,
            "paid_out": paid_out,
            "billing_records_count": len(billings)
        },
        "billing_history": [
            {
                "name": b.name, "payout_sheet": b.payout_sheet,
                "billing_cycle": b.billing_cycle,
                "start_date": str(b.start_date) if b.start_date else None,
                "end_date": str(b.end_date) if b.end_date else None,
                "gross_sales": float(b.gross_sales or 0),
                "platform_commission_rate": float(b.platform_commission_rate or 0),
                "platform_commission": float(b.platform_commission or 0),
                "gst_on_commission": float(b.gst_on_commission or 0),
                "refunds": float(b.refunds or 0),
                "net_earnings": float(b.net_earnings or 0),
                "tds_rate": float(b.tds_rate or 0),
                "tds_amount": float(b.tds_amount or 0),
                "net_payout": float(b.net_payout or 0),
                "status": b.status,
                "paid_on": str(b.paid_on) if b.paid_on else None,
                "payment_reference": b.payment_reference,
                "payment_mode": b.payment_mode,
                "created_at": str(b.creation) if b.creation else None
            }
            for b in billings
        ],
        "recent_transactions": [
            {
                "payment_name": t.name, "payment_id": t.payment_id,
                "student_name": t.student_name, "student_email": t.member,
                "item_type": t.item_type, "item_name": t.item_name,
                "amount": float(t.amount or 0),
                "currency": t.currency or "INR",
                "created_at": str(t.creation) if t.creation else None
            }
            for t in recent_txn
        ],
        "settings": {
            "tds_threshold": settings.tds_threshold,
            "tds_rate": settings.tds_rate,
            "default_commission_rate": settings.default_commission_rate,
            "apply_gst_on_commission": bool(settings.apply_gst_on_commission),
            "commission_tiers": settings.commission_tiers,
            "min_payout_threshold": settings.min_payout_threshold
        }
    }, "Instructor billing dashboard fetched.")


@frappe.whitelist()
def get_all_instructor_payouts(page=1, page_size=20, status=None, billing_cycle=None):
    """
    Admin: List all LMS Instructor Billing records across all instructors
    for the admin billing management dashboard.

    Args:
        page         - Page number (default 1)
        page_size    - Records per page (default 20)
        status       - Filter: Draft / Approved / Paid / Hold / Cancelled
        billing_cycle - Filter: Monthly / Weekly / etc
    """
    _require_admin()
    page      = int(page or 1)
    page_size = int(page_size or 20)
    offset    = (page - 1) * page_size

    filters = {}
    if status:
        filters["status"] = status
    if billing_cycle:
        filters["billing_cycle"] = billing_cycle

    total = frappe.db.count("LMS Instructor Billing", filters)
    rows  = frappe.get_all(
        "LMS Instructor Billing",
        filters=filters,
        fields=[
            "name", "instructor", "instructor_name", "payout_sheet",
            "billing_cycle", "start_date", "end_date",
            "gross_sales", "platform_commission", "gst_on_commission",
            "net_earnings", "tds_amount", "net_payout",
            "status", "paid_on", "payment_reference", "creation"
        ],
        order_by="creation desc",
        limit=page_size, start=offset
    )

    agg = frappe.db.sql(
        """SELECT
               COALESCE(SUM(gross_sales), 0) as total_gross,
               COALESCE(SUM(platform_commission + gst_on_commission), 0) as total_commission,
               COALESCE(SUM(tds_amount), 0) as total_tds,
               COALESCE(SUM(net_payout), 0) as total_net_payout,
               COALESCE(SUM(CASE WHEN status='Paid' THEN net_payout ELSE 0 END), 0) as total_paid,
               COALESCE(SUM(CASE WHEN status IN ('Approved','Draft') THEN net_payout ELSE 0 END), 0) as total_pending,
               COUNT(DISTINCT instructor) as instructor_count,
               COUNT(*) as billing_count
           FROM `tabLMS Instructor Billing`""",
        as_dict=True
    )
    s = agg[0] if agg else {}

    return success({
        "billings": [
            {
                "name": r.name, "instructor": r.instructor,
                "instructor_name": r.instructor_name, "payout_sheet": r.payout_sheet,
                "billing_cycle": r.billing_cycle,
                "start_date": str(r.start_date) if r.start_date else None,
                "end_date": str(r.end_date) if r.end_date else None,
                "gross_sales": float(r.gross_sales or 0),
                "platform_commission": float(r.platform_commission or 0),
                "gst_on_commission": float(r.gst_on_commission or 0),
                "net_earnings": float(r.net_earnings or 0),
                "tds_amount": float(r.tds_amount or 0),
                "net_payout": float(r.net_payout or 0),
                "status": r.status,
                "paid_on": str(r.paid_on) if r.paid_on else None,
                "payment_reference": r.payment_reference,
                "created_at": str(r.creation) if r.creation else None
            }
            for r in rows
        ],
        "pagination": {
            "total": total, "page": page, "page_size": page_size,
            "total_pages": -(-total // page_size)
        },
        "aggregate_stats": {
            "total_gross_sales": float(s.get("total_gross") or 0),
            "total_platform_revenue": float(s.get("total_commission") or 0),
            "total_tds_held": float(s.get("total_tds") or 0),
            "total_net_payout": float(s.get("total_net_payout") or 0),
            "total_paid_out": float(s.get("total_paid") or 0),
            "total_pending_payout": float(s.get("total_pending") or 0),
            "instructor_count": int(s.get("instructor_count") or 0),
            "billing_count": int(s.get("billing_count") or 0)
        }
    }, "Admin instructor billing list fetched.")


@frappe.whitelist()
def get_instructor_billing_settings():
    """Admin: Return current LMS Instructor Billing Settings."""
    _require_admin()
    settings = _get_billing_settings()
    return success({
        "tds_threshold": settings.tds_threshold,
        "tds_rate": settings.tds_rate,
        "default_commission_rate": settings.default_commission_rate,
        "apply_gst_on_commission": bool(settings.apply_gst_on_commission),
        "commission_tiers": settings.commission_tiers,
        "min_payout_threshold": settings.min_payout_threshold,
        "billing_cycle": settings.billing_cycle
    }, "Billing settings fetched.")


@frappe.whitelist()
def update_instructor_billing_settings(
    tds_threshold=None, tds_rate=None, default_commission_rate=None,
    apply_gst_on_commission=None, min_payout_threshold=None,
    billing_cycle=None, commission_tiers=None
):
    """
    Admin: Update LMS Instructor Billing Settings.

    commission_tiers format: JSON array of [{label, gross_threshold, commission_rate}]
    """
    _require_admin()
    try:
        s = frappe.get_single("LMS Instructor Billing Settings")
    except Exception:
        s = frappe.new_doc("LMS Instructor Billing Settings")

    if tds_threshold          is not None: s.tds_threshold = float(tds_threshold)
    if tds_rate               is not None: s.tds_rate = float(tds_rate)
    if default_commission_rate is not None: s.default_commission_rate = float(default_commission_rate)
    if apply_gst_on_commission is not None: s.apply_gst_on_commission = int(apply_gst_on_commission)
    if min_payout_threshold   is not None: s.min_payout_threshold = float(min_payout_threshold)
    if billing_cycle          is not None: s.billing_cycle = billing_cycle

    if commission_tiers is not None:
        import json as _j
        if isinstance(commission_tiers, str):
            commission_tiers = _j.loads(commission_tiers)
        s.set("commission_tiers", [])
        for t in commission_tiers:
            s.append("commission_tiers", {
                "label": t.get("label", ""),
                "gross_threshold": float(t.get("gross_threshold", 0)),
                "commission_rate": float(t.get("commission_rate", 0))
            })

    s.save(ignore_permissions=True)
    frappe.db.commit()
    return get_instructor_billing_settings()


@frappe.whitelist(allow_guest=True)
def preview_instructor_billing(instructor=None, start_date=None, end_date=None):
    """
    Instructor self-service: Live preview of earnings estimate for a date range
    WITHOUT creating or saving any records.

    Defaults to the current calendar month if dates not provided.
    """
    user = frappe.session.user
    if user == "Guest":
        return error("Authentication required.", 401)

    target = instructor if instructor else user
    if target != user:
        roles = frappe.get_roles(user)
        if not any(r in roles for r in ["Administrator", "System Manager", "Moderator"]):
            return error("Permission denied.", 403)

    from frappe.utils import get_first_day, today
    if not start_date:
        start_date = str(get_first_day(today()))
    if not end_date:
        end_date = str(today())

    settings = _get_billing_settings()
    data = _calculate_instructor_financials(target, start_date, end_date, settings)

    if data is None:
        return success({
            "instructor": target, "message": "No courses or batches found.",
            "gross_sales": 0, "net_payout": 0
        }, "No content found.")

    return success({
        "instructor": target,
        "instructor_name": data["instructor_name"],
        "period": {"start_date": start_date, "end_date": end_date},
        "breakdown": {
            "gross_sales": data["gross_sales"],
            "course_sales": data["course_gross"],
            "batch_sales": data["batch_gross"],
            "total_transactions": data["total_sales"],
            "platform_commission_rate": data["platform_commission_rate"],
            "platform_commission": data["platform_commission"],
            "gst_on_commission": data["gst_on_commission"],
            "gst_rate": 18.0,
            "refunds": data["refunds"],
            "net_earnings": data["net_earnings"],
            "tds_rate": data["tds_rate"],
            "tds_amount": data["tds_amount"],
            "net_payout": data["net_payout"]
        },
        "settings_applied": {
            "tds_threshold": settings.tds_threshold,
            "commission_tiers": settings.commission_tiers,
            "apply_gst_on_commission": bool(settings.apply_gst_on_commission)
        }
    }, "Billing preview calculated.")


# ═══════════════════════════════════════════════════════════════════════════
# PAYMENT SLIP & INSTRUCTOR PAYOUT SLIP PDF GENERATION
# ═══════════════════════════════════════════════════════════════════════════

def _build_student_payment_slip_html(pay):
    """Generates clean, printable HTML for a student LMS Payment receipt/slip."""
    from frappe.utils import format_date, format_time, flt

    item_type_label = "Course"
    item_title = pay.payment_for_document
    if pay.payment_for_document_type == "LMS Course":
        item_type_label = "Course"
        course_title = frappe.db.get_value("LMS Course", pay.payment_for_document, "title")
        if course_title:
            item_title = course_title
    elif pay.payment_for_document_type == "LMS Batch":
        item_type_label = "Batch"
        batch_title = frappe.db.get_value("LMS Batch", pay.payment_for_document, "title")
        if batch_title:
            item_title = batch_title
    elif pay.payment_for_document_type == "LMS Certificate":
        item_type_label = "Certificate"

    addr_line = ""
    city_state_zip = ""
    country = "India"
    phone = ""
    if getattr(pay, "address", None) and frappe.db.exists("Address", pay.address):
        addr = frappe.get_doc("Address", pay.address)
        parts = [p for p in [addr.address_line1, addr.address_line2] if p]
        addr_line = ", ".join(parts)
        cs_parts = [p for p in [addr.city, addr.state, addr.pincode] if p]
        city_state_zip = ", ".join(cs_parts)
        country = addr.country or "India"
        phone = addr.phone or ""

    date_str = format_date(pay.creation) if pay.creation else ""
    time_str = format_time(pay.creation) if pay.creation else ""

    orig_amt = flt(getattr(pay, "original_amount", 0) or pay.amount or 0)
    disc_amt = flt(getattr(pay, "discount_amount", 0) or 0)
    paid_amt = flt(pay.amount or 0)
    tax_amt  = flt(getattr(pay, "amount_with_gst", 0) or 0)
    coupon   = getattr(pay, "coupon_code", None)

    phone_html = f"Phone: {phone}<br>" if phone else ""
    addr_html  = f"Address: {addr_line}<br>" if addr_line else ""
    csz_html   = f"{city_state_zip}, {country}<br>" if city_state_zip else ""
    gstin_html = f"GSTIN: {pay.gstin}<br>" if getattr(pay, "gstin", None) else ""
    pan_html   = f"PAN: {pay.pan}<br>" if getattr(pay, "pan", None) else ""

    disc_row = ""
    if disc_amt > 0:
        disc_row = f"""<tr>
            <td class="calc-label">Discount Applied ({coupon or 'Promo'}):</td>
            <td class="calc-val" style="color: #16a34a;">- &#8377; {disc_amt:,.2f}</td>
          </tr>"""

    tax_row = ""
    if tax_amt > 0:
        tax_row = f"""<tr>
            <td class="calc-label">Taxes / GST:</td>
            <td class="calc-val">&#8377; {tax_amt:,.2f}</td>
          </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Payment Receipt - {pay.name}</title>
<style>
  @page {{
    size: A4;
    margin: 15mm;
  }}
  * {{
    box-sizing: border-box;
    -webkit-print-color-adjust: exact !important;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    color: #1e293b;
    background: #ffffff;
    margin: 0;
    padding: 0;
    font-size: 13px;
    line-height: 1.5;
  }}
  .slip-container {{
    max-width: 100%;
    margin: 0 auto;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    overflow: hidden;
  }}
  .header-bar {{
    background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
    color: #ffffff;
    padding: 24px 30px;
  }}
  .brand-row {{
    display: table;
    width: 100%;
  }}
  .brand-left {{
    display: table-cell;
    vertical-align: middle;
  }}
  .brand-right {{
    display: table-cell;
    vertical-align: middle;
    text-align: right;
  }}
  .brand-name {{
    font-size: 22px;
    font-weight: 800;
    letter-spacing: -0.5px;
    text-transform: uppercase;
  }}
  .brand-sub {{
    font-size: 12px;
    opacity: 0.85;
    margin-top: 2px;
  }}
  .badge-paid {{
    display: inline-block;
    background: #22c55e;
    color: #ffffff;
    font-size: 12px;
    font-weight: 700;
    padding: 4px 14px;
    border-radius: 20px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }}
  .receipt-title {{
    font-size: 18px;
    font-weight: 700;
    margin-top: 14px;
    color: #ffffff;
    letter-spacing: 0.2px;
  }}
  .meta-bar {{
    background: #f8fafc;
    border-bottom: 1px solid #e2e8f0;
    padding: 16px 30px;
  }}
  .meta-table {{
    width: 100%;
    border-collapse: collapse;
  }}
  .meta-table td {{
    padding: 4px 8px;
    font-size: 12px;
  }}
  .meta-label {{
    color: #64748b;
    font-weight: 600;
    width: 20%;
  }}
  .meta-val {{
    color: #0f172a;
    font-weight: 700;
    width: 30%;
  }}
  .content-area {{
    padding: 24px 30px;
  }}
  .party-grid {{
    display: table;
    width: 100%;
    margin-bottom: 24px;
  }}
  .party-box {{
    display: table-cell;
    width: 50%;
    vertical-align: top;
    padding: 16px;
    background: #f8fafc;
    border-radius: 8px;
    border: 1px solid #e2e8f0;
  }}
  .party-box-spacer {{
    display: table-cell;
    width: 4%;
  }}
  .party-heading {{
    font-size: 11px;
    font-weight: 800;
    color: #3b82f6;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin-bottom: 8px;
    border-bottom: 1px solid #e2e8f0;
    padding-bottom: 4px;
  }}
  .party-text {{
    font-size: 12px;
    color: #334155;
    line-height: 1.6;
  }}
  .party-title {{
    font-weight: 700;
    font-size: 13px;
    color: #0f172a;
  }}
  .item-table {{
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 24px;
  }}
  .item-table th {{
    background: #f1f5f9;
    color: #475569;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 10px 14px;
    border: 1px solid #e2e8f0;
    text-align: left;
  }}
  .item-table td {{
    padding: 12px 14px;
    border: 1px solid #e2e8f0;
    font-size: 12px;
    color: #334155;
  }}
  .text-right {{
    text-align: right;
  }}
  .totals-wrapper {{
    display: table;
    width: 100%;
    margin-bottom: 24px;
  }}
  .totals-left {{
    display: table-cell;
    width: 55%;
    vertical-align: top;
    padding-right: 20px;
  }}
  .totals-right {{
    display: table-cell;
    width: 45%;
    vertical-align: top;
  }}
  .calculation-table {{
    width: 100%;
    border-collapse: collapse;
  }}
  .calculation-table td {{
    padding: 6px 10px;
    font-size: 12px;
  }}
  .calc-label {{
    color: #64748b;
  }}
  .calc-val {{
    font-weight: 600;
    text-align: right;
    color: #0f172a;
  }}
  .calc-total-row td {{
    border-top: 2px solid #3b82f6;
    padding-top: 10px;
    font-size: 14px;
    font-weight: 800;
    color: #1d4ed8;
  }}
  .note-box {{
    background: #eff6ff;
    border: 1px dashed #bfdbfe;
    border-radius: 8px;
    padding: 12px 14px;
    font-size: 11px;
    color: #1e40af;
    line-height: 1.5;
  }}
  .footer-bar {{
    border-top: 1px solid #e2e8f0;
    background: #f8fafc;
    padding: 16px 30px;
    font-size: 11px;
    color: #64748b;
    text-align: center;
    line-height: 1.6;
  }}
</style>
</head>
<body>
<div class="slip-container">
  <div class="header-bar">
    <div class="brand-row">
      <div class="brand-left">
        <div class="brand-name">STRIDENEX LMS</div>
        <div class="brand-sub">Stridenex Technologies Pvt. Ltd. &bull; devlms.stridenex.ai</div>
      </div>
      <div class="brand-right">
        <div class="badge-paid">PAID &bull; SUCCESS</div>
      </div>
    </div>
    <div class="receipt-title">Payment Receipt & Tax Invoice</div>
  </div>

  <div class="meta-bar">
    <table class="meta-table">
      <tr>
        <td class="meta-label">Receipt / Slip No:</td>
        <td class="meta-val">{pay.name}</td>
        <td class="meta-label">Transaction Date:</td>
        <td class="meta-val">{date_str} {time_str}</td>
      </tr>
      <tr>
        <td class="meta-label">Gateway Payment ID:</td>
        <td class="meta-val">{pay.payment_id or "N/A"}</td>
        <td class="meta-label">Gateway Order ID:</td>
        <td class="meta-val">{pay.order_id or "N/A"}</td>
      </tr>
      <tr>
        <td class="meta-label">Payment Mode:</td>
        <td class="meta-val">Online (Razorpay Secure)</td>
        <td class="meta-label">Currency:</td>
        <td class="meta-val">{pay.currency or "INR"}</td>
      </tr>
    </table>
  </div>

  <div class="content-area">
    <div class="party-grid">
      <div class="party-box">
        <div class="party-heading">Billed To (Student)</div>
        <div class="party-title">{pay.billing_name or pay.member}</div>
        <div class="party-text">
          Email: {pay.member}<br>
          {phone_html}
          {addr_html}
          {csz_html}
          {gstin_html}
          {pan_html}
        </div>
      </div>
      <div class="party-box-spacer"></div>
      <div class="party-box">
        <div class="party-heading">Issued By</div>
        <div class="party-title">Stridenex Technologies Pvt. Ltd.</div>
        <div class="party-text">
          Learning & Development Solutions<br>
          Platform: devlms.stridenex.ai<br>
          Support Desk: support@stridenex.ai<br>
          Jurisdiction: India
        </div>
      </div>
    </div>

    <table class="item-table">
      <thead>
        <tr>
          <th style="width: 8%;">#</th>
          <th style="width: 48%;">Description</th>
          <th style="width: 14%;">Type</th>
          <th style="width: 15%; text-align: right;">List Price</th>
          <th style="width: 15%; text-align: right;">Amount</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>1</td>
          <td>
            <strong>{item_title}</strong><br>
            <span style="font-size: 11px; color: #64748b;">Ref Code: {pay.payment_for_document}</span>
          </td>
          <td>{item_type_label}</td>
          <td class="text-right">&#8377; {orig_amt:,.2f}</td>
          <td class="text-right">&#8377; {paid_amt:,.2f}</td>
        </tr>
      </tbody>
    </table>

    <div class="totals-wrapper">
      <div class="totals-left">
        <div class="note-box">
          <strong>Enrollment Confirmation:</strong><br>
          Payment successfully verified. You have full lifetime access to the purchased material, lessons, quizzes, and digital resources.
        </div>
      </div>
      <div class="totals-right">
        <table class="calculation-table">
          <tr>
            <td class="calc-label">Subtotal:</td>
            <td class="calc-val">&#8377; {orig_amt:,.2f}</td>
          </tr>
          {disc_row}
          {tax_row}
          <tr class="calc-total-row">
            <td>Total Paid:</td>
            <td class="calc-val">&#8377; {paid_amt:,.2f}</td>
          </tr>
        </table>
      </div>
    </div>
  </div>

  <div class="footer-bar">
    This is an authentic, computer-generated receipt issued by Stridenex LMS. No physical signature is required.<br>
    Questions about this transaction? Contact support at support@stridenex.ai
  </div>
</div>
</body>
</html>"""


def _build_instructor_payout_slip_html(b):
    """Generates clean, printable HTML for an instructor payout advice/slip."""
    from frappe.utils import format_date, flt

    start_str = format_date(b.start_date) if getattr(b, "start_date", None) else "N/A"
    end_str   = format_date(b.end_date)   if getattr(b, "end_date", None)   else "N/A"
    paid_str  = format_date(b.paid_on)    if getattr(b, "paid_on", None)    else "Pending"

    gross_sales  = flt(getattr(b, "gross_sales", 0) or 0)
    comm_rate    = flt(getattr(b, "platform_commission_rate", 0) or 0)
    comm_amt     = flt(getattr(b, "platform_commission", 0) or 0)
    gst_amt      = flt(getattr(b, "gst_on_commission", 0) or 0)
    refunds_amt  = flt(getattr(b, "refunds", 0) or 0)
    net_earnings = flt(getattr(b, "net_earnings", 0) or 0)
    tds_rate     = flt(getattr(b, "tds_rate", 0) or 0)
    tds_amt      = flt(getattr(b, "tds_amount", 0) or 0)
    net_payout   = flt(getattr(b, "net_payout", 0) or 0)

    status_badge_bg = "#22c55e" if b.status == "Paid" else ("#3b82f6" if b.status == "Approved" else "#eab308")

    refund_row = ""
    if refunds_amt > 0:
        refund_row = f"""<tr>
          <td>04</td>
          <td>Refunds & Reversals Adjustment<br><span style="font-size: 11px; color: #64748b;">Enrollments cancelled or chargebacks</span></td>
          <td>Actuals</td>
          <td class="text-right" style="color: #dc2626;">- &#8377; {refunds_amt:,.2f}</td>
        </tr>"""

    tds_desc = "Deducted per Income Tax guidelines" if tds_amt > 0 else "Exempt (under annual threshold)"
    tds_display = f"- &#8377; {tds_amt:,.2f}" if tds_amt > 0 else "NIL"

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Instructor Payout Slip - {b.name}</title>
<style>
  @page {{
    size: A4;
    margin: 15mm;
  }}
  * {{
    box-sizing: border-box;
    -webkit-print-color-adjust: exact !important;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    color: #1e293b;
    background: #ffffff;
    margin: 0;
    padding: 0;
    font-size: 13px;
    line-height: 1.5;
  }}
  .slip-container {{
    max-width: 100%;
    margin: 0 auto;
    border: 1px solid #cbd5e1;
    border-radius: 12px;
    overflow: hidden;
  }}
  .header-bar {{
    background: linear-gradient(135deg, #1e1b4b 0%, #312e81 60%, #4338ca 100%);
    color: #ffffff;
    padding: 24px 30px;
  }}
  .brand-row {{
    display: table;
    width: 100%;
  }}
  .brand-left {{
    display: table-cell;
    vertical-align: middle;
  }}
  .brand-right {{
    display: table-cell;
    vertical-align: middle;
    text-align: right;
  }}
  .brand-name {{
    font-size: 22px;
    font-weight: 800;
    letter-spacing: -0.5px;
    text-transform: uppercase;
  }}
  .brand-sub {{
    font-size: 12px;
    opacity: 0.85;
    margin-top: 2px;
  }}
  .badge-status {{
    display: inline-block;
    background: {status_badge_bg};
    color: #ffffff;
    font-size: 12px;
    font-weight: 700;
    padding: 4px 14px;
    border-radius: 20px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }}
  .advice-title {{
    font-size: 18px;
    font-weight: 700;
    margin-top: 14px;
    color: #ffffff;
    letter-spacing: 0.2px;
  }}
  .meta-bar {{
    background: #f8fafc;
    border-bottom: 1px solid #e2e8f0;
    padding: 16px 30px;
  }}
  .meta-table {{
    width: 100%;
    border-collapse: collapse;
  }}
  .meta-table td {{
    padding: 4px 8px;
    font-size: 12px;
  }}
  .meta-label {{
    color: #64748b;
    font-weight: 600;
    width: 22%;
  }}
  .meta-val {{
    color: #0f172a;
    font-weight: 700;
    width: 28%;
  }}
  .content-area {{
    padding: 24px 30px;
  }}
  .party-grid {{
    display: table;
    width: 100%;
    margin-bottom: 24px;
  }}
  .party-box {{
    display: table-cell;
    width: 50%;
    vertical-align: top;
    padding: 16px;
    background: #f8fafc;
    border-radius: 8px;
    border: 1px solid #e2e8f0;
  }}
  .party-box-spacer {{
    display: table-cell;
    width: 4%;
  }}
  .party-heading {{
    font-size: 11px;
    font-weight: 800;
    color: #4f46e5;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin-bottom: 8px;
    border-bottom: 1px solid #e2e8f0;
    padding-bottom: 4px;
  }}
  .party-text {{
    font-size: 12px;
    color: #334155;
    line-height: 1.6;
  }}
  .party-title {{
    font-weight: 700;
    font-size: 13px;
    color: #0f172a;
  }}
  .breakdown-table {{
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 24px;
  }}
  .breakdown-table th {{
    background: #f1f5f9;
    color: #334155;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 10px 14px;
    border: 1px solid #e2e8f0;
    text-align: left;
  }}
  .breakdown-table td {{
    padding: 10px 14px;
    border: 1px solid #e2e8f0;
    font-size: 12px;
    color: #334155;
  }}
  .text-right {{
    text-align: right;
  }}
  .row-subtotal td {{
    background: #faf5ff;
    font-weight: 700;
    color: #6b21a8;
  }}
  .row-highlight td {{
    background: #ecfdf5;
    font-size: 14px;
    font-weight: 800;
    color: #065f46;
    border-top: 2px solid #10b981;
    border-bottom: 2px solid #10b981;
  }}
  .payout-box {{
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 24px;
  }}
  .payout-box-title {{
    font-size: 11px;
    font-weight: 800;
    color: #475569;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 6px;
  }}
  .payout-grid {{
    display: table;
    width: 100%;
  }}
  .payout-col {{
    display: table-cell;
    width: 33.33%;
    vertical-align: top;
    font-size: 12px;
  }}
  .footer-bar {{
    border-top: 1px solid #e2e8f0;
    background: #f8fafc;
    padding: 16px 30px;
    font-size: 11px;
    color: #64748b;
    text-align: center;
    line-height: 1.6;
  }}
</style>
</head>
<body>
<div class="slip-container">
  <div class="header-bar">
    <div class="brand-row">
      <div class="brand-left">
        <div class="brand-name">STRIDENEX LMS</div>
        <div class="brand-sub">Stridenex Technologies Pvt. Ltd. &bull; Partner Settlement Division</div>
      </div>
      <div class="brand-right">
        <div class="badge-status">{b.status}</div>
      </div>
    </div>
    <div class="advice-title">Instructor Revenue Settlement Advice & Payout Slip</div>
  </div>

  <div class="meta-bar">
    <table class="meta-table">
      <tr>
        <td class="meta-label">Billing Voucher No:</td>
        <td class="meta-val">{b.name}</td>
        <td class="meta-label">Billing Cycle:</td>
        <td class="meta-val">{getattr(b, 'billing_cycle', None) or "Monthly"}</td>
      </tr>
      <tr>
        <td class="meta-label">Master Payout Sheet:</td>
        <td class="meta-val">{getattr(b, 'payout_sheet', None) or "Individual"}</td>
        <td class="meta-label">Settlement Period:</td>
        <td class="meta-val">{start_str} to {end_str}</td>
      </tr>
      <tr>
        <td class="meta-label">Payment Mode:</td>
        <td class="meta-val">{getattr(b, 'payment_mode', None) or "NEFT / Bank Transfer"}</td>
        <td class="meta-label">Disbursement Date:</td>
        <td class="meta-val">{paid_str}</td>
      </tr>
    </table>
  </div>

  <div class="content-area">
    <div class="party-grid">
      <div class="party-box">
        <div class="party-heading">Beneficiary (Instructor)</div>
        <div class="party-title">{b.instructor_name or b.instructor}</div>
        <div class="party-text">
          Registered Email / ID: {b.instructor}<br>
          Instructor ID: {b.instructor}<br>
          Status: Verified LMS Partner
        </div>
      </div>
      <div class="party-box-spacer"></div>
      <div class="party-box">
        <div class="party-heading">Disbursing Entity</div>
        <div class="party-title">Stridenex Technologies Pvt. Ltd.</div>
        <div class="party-text">
          LMS Platform Operations<br>
          devlms.stridenex.ai<br>
          Instructor Support: partners@stridenex.ai
        </div>
      </div>
    </div>

    <table class="breakdown-table">
      <thead>
        <tr>
          <th style="width: 10%;">Line #</th>
          <th style="width: 50%;">Earnings & Deductions Component</th>
          <th style="width: 18%;">Basis / Rate</th>
          <th style="width: 22%; text-align: right;">Amount (INR)</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>01</td>
          <td><strong>Gross Enrollments & Course Sales</strong><br><span style="font-size: 11px; color: #64748b;">Total student fee payments during settlement period</span></td>
          <td>100.0%</td>
          <td class="text-right">&#8377; {gross_sales:,.2f}</td>
        </tr>
        <tr>
          <td>02</td>
          <td>Platform Commission Share<br><span style="font-size: 11px; color: #64748b;">Platform infrastructure, hosting & payment processing</span></td>
          <td>{comm_rate:.1f}%</td>
          <td class="text-right" style="color: #dc2626;">- &#8377; {comm_amt:,.2f}</td>
        </tr>
        <tr>
          <td>03</td>
          <td>GST on Platform Commission<br><span style="font-size: 11px; color: #64748b;">Goods and Services Tax on platform fees</span></td>
          <td>18.0%</td>
          <td class="text-right" style="color: #dc2626;">- &#8377; {gst_amt:,.2f}</td>
        </tr>
        {refund_row}
        <tr class="row-subtotal">
          <td colspan="3">Net Earnings Before Tax (TDS)</td>
          <td class="text-right">&#8377; {net_earnings:,.2f}</td>
        </tr>
        <tr>
          <td>05</td>
          <td>TDS Deducted (Sec 194J)<br><span style="font-size: 11px; color: #64748b;">{tds_desc}</span></td>
          <td>{tds_rate:.1f}%</td>
          <td class="text-right" style="color: #dc2626;">{tds_display}</td>
        </tr>
        <tr class="row-highlight">
          <td colspan="3">NET PAYOUT DISBURSED / TRANSFERRED</td>
          <td class="text-right">&#8377; {net_payout:,.2f}</td>
        </tr>
      </tbody>
    </table>

    <div class="payout-box">
      <div class="payout-box-title">Bank Settlement & UTR Details</div>
      <div class="payout-grid">
        <div class="payout-col">
          <span style="color: #64748b;">Payment Status:</span> <strong>{b.status}</strong>
        </div>
        <div class="payout-col">
          <span style="color: #64748b;">Transfer Mode:</span> <strong>{getattr(b, 'payment_mode', None) or "NEFT"}</strong>
        </div>
        <div class="payout-col">
          <span style="color: #64748b;">UTR / Bank Ref:</span> <strong style="font-family: monospace;">{getattr(b, 'payment_reference', None) or "Pending"}</strong>
        </div>
      </div>
    </div>
  </div>

  <div class="footer-bar">
    This settlement advice confirms the revenue share distribution computed per platform agreement terms.<br>
    Issued by Stridenex Technologies Pvt. Ltd. &bull; Inquiries: partners@stridenex.ai
  </div>
</div>
</body>
</html>"""


def _can_user_access_payment(pay, user):
    """
    Check if a user has permission to view/download a payment slip:
      1. Platform Admin / System Manager / LMS Admin / Moderator -> True
      2. Student who paid (pay.member or pay.user) -> True
      3. Instructor who teaches or owns the purchased Course / Batch -> True
    """
    if not user or user == "Guest":
        return False

    roles = frappe.get_roles(user)
    if any(r in roles for r in ["Administrator", "System Manager", "LMS Admin", "Moderator"]):
        return True

    if user == pay.member or getattr(pay, "user", None) == user:
        return True

    doc_type = pay.payment_for_document_type
    doc_name = pay.payment_for_document

    # Direct checks on Course / Batch
    if doc_type == "LMS Course":
        if frappe.db.get_value("LMS Course", doc_name, "owner") == user:
            return True
        if frappe.db.exists("Course Instructor", {"parent": doc_name, "instructor": user}):
            return True
    elif doc_type == "LMS Batch":
        if frappe.db.get_value("LMS Batch", doc_name, "owner") == user:
            return True
        if frappe.db.exists("Course Instructor", {"parent": doc_name, "instructor": user}):
            return True

    # General instructor courses and batches check
    c_names, b_names = _get_instructor_courses_and_batches(user)
    if (doc_type == "LMS Course" and doc_name in c_names) or (doc_type == "LMS Batch" and doc_name in b_names):
        return True

    return False


@frappe.whitelist(allow_guest=True)
def download_payment_slip(payment_name, as_attachment=0):
    """
    Generate and serve the official Payment Receipt / Slip PDF.
    If as_attachment=1: forces browser download with Content-Disposition: attachment.
    If as_attachment=0: serves inline PDF (perfect for modal popups, iframes, and browser viewing).
    """
    from frappe.utils.pdf import get_pdf
    from frappe.utils import cint

    if not payment_name or not frappe.db.exists("LMS Payment", payment_name):
        return error("Payment record not found.", 404)

    pay = frappe.get_doc("LMS Payment", payment_name)
    user = frappe.session.user

    # Permission check: student who paid, course/batch instructor, or platform admin
    if user != "Guest":
        if not _can_user_access_payment(pay, user):
            return error("Permission denied.", 403)

    try:
        html = _build_student_payment_slip_html(pay)
        pdf_bytes = get_pdf(html)

        filename = f"Payment_Slip_{pay.name}.pdf"
        frappe.response.filecontent = pdf_bytes
        frappe.response.filename = filename

        if cint(as_attachment):
            frappe.response.type = "download"
            frappe.response.display_content_as = "attachment"
            frappe.response.content_type = "application/pdf"
        else:
            frappe.response.type = "pdf"

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "download_payment_slip")
        return error(f"Failed to generate payment slip PDF: {str(e)}", 500)


@frappe.whitelist(allow_guest=True)
def get_payment_slip_data(payment_name):
    """
    API endpoint returning payment slip data for frontend modal popups.
    Includes base64-encoded PDF, direct view/download URLs, and key transaction details.
    """
    import base64
    from frappe.utils.pdf import get_pdf
    from frappe.utils import format_date, format_time, flt

    if not payment_name or not frappe.db.exists("LMS Payment", payment_name):
        return error("Payment record not found.", 404)

    pay = frappe.get_doc("LMS Payment", payment_name)
    user = frappe.session.user

    # Permission check: student who paid, course/batch instructor, or platform admin
    if user != "Guest":
        if not _can_user_access_payment(pay, user):
            return error("Permission denied.", 403)

    try:
        html = _build_student_payment_slip_html(pay)
        pdf_bytes = get_pdf(html)
        pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

        item_title = pay.payment_for_document
        if pay.payment_for_document_type == "LMS Course":
            item_title = frappe.db.get_value("LMS Course", pay.payment_for_document, "title") or item_title
        elif pay.payment_for_document_type == "LMS Batch":
            item_title = frappe.db.get_value("LMS Batch", pay.payment_for_document, "title") or item_title

        view_url = f"/api/method/lms.lms.stride_lms.download_payment_slip?payment_name={pay.name}"
        dl_url   = f"/api/method/lms.lms.stride_lms.download_payment_slip?payment_name={pay.name}&as_attachment=1"

        return success({
            "payment_name": pay.name,
            "filename": f"Payment_Slip_{pay.name}.pdf",
            "pdf_base64": pdf_b64,
            "pdf_data_url": f"data:application/pdf;base64,{pdf_b64}",
            "view_url": view_url,
            "download_url": dl_url,
            "details": {
                "name": pay.name,
                "student_name": pay.billing_name or pay.member,
                "student_email": pay.member,
                "payment_id": pay.payment_id,
                "order_id": pay.order_id,
                "item_type": pay.payment_for_document_type,
                "item_id": pay.payment_for_document,
                "item_title": item_title,
                "amount": flt(pay.amount or 0),
                "original_amount": flt(getattr(pay, "original_amount", 0) or pay.amount or 0),
                "discount_amount": flt(getattr(pay, "discount_amount", 0) or 0),
                "coupon_code": getattr(pay, "coupon_code", None),
                "currency": pay.currency or "INR",
                "payment_received": bool(pay.payment_received),
                "date": format_date(pay.creation) if pay.creation else "",
                "time": format_time(pay.creation) if pay.creation else ""
            }
        }, "Payment slip data generated.")

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_payment_slip_data")
        return error(f"Failed to generate payment slip data: {str(e)}", 500)


@frappe.whitelist(allow_guest=True)
def download_instructor_payout_slip(billing_name, as_attachment=0):
    """
    Generate and serve the official Instructor Payout Advice / Slip PDF.
    If as_attachment=1: forces browser download with Content-Disposition: attachment.
    If as_attachment=0: serves inline PDF (perfect for modal popups, iframes, and browser viewing).
    """
    from frappe.utils.pdf import get_pdf
    from frappe.utils import cint

    if not billing_name or not frappe.db.exists("LMS Instructor Billing", billing_name):
        return error("Billing record not found.", 404)

    b = frappe.get_doc("LMS Instructor Billing", billing_name)
    user = frappe.session.user

    # Permission check: instructor or admin can view
    if user != "Guest":
        roles = frappe.get_roles(user)
        is_admin = any(r in roles for r in ["Administrator", "System Manager", "LMS Admin", "Moderator"])
        if user != b.instructor and not is_admin:
            return error("Permission denied.", 403)

    try:
        html = _build_instructor_payout_slip_html(b)
        pdf_bytes = get_pdf(html)

        filename = f"Payout_Slip_{b.name}.pdf"
        frappe.response.filecontent = pdf_bytes
        frappe.response.filename = filename

        if cint(as_attachment):
            frappe.response.type = "download"
            frappe.response.display_content_as = "attachment"
            frappe.response.content_type = "application/pdf"
        else:
            frappe.response.type = "pdf"

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "download_instructor_payout_slip")
        return error(f"Failed to generate payout slip PDF: {str(e)}", 500)


@frappe.whitelist(allow_guest=True)
def get_instructor_payout_slip_data(billing_name):
    """
    API endpoint returning instructor payout slip data for frontend modal popups.
    Includes base64-encoded PDF, direct view/download URLs, and financial breakdown details.
    """
    import base64
    from frappe.utils.pdf import get_pdf
    from frappe.utils import format_date, flt

    if not billing_name or not frappe.db.exists("LMS Instructor Billing", billing_name):
        return error("Billing record not found.", 404)

    b = frappe.get_doc("LMS Instructor Billing", billing_name)
    user = frappe.session.user

    if user != "Guest":
        roles = frappe.get_roles(user)
        is_admin = any(r in roles for r in ["Administrator", "System Manager", "LMS Admin", "Moderator"])
        if user != b.instructor and not is_admin:
            return error("Permission denied.", 403)

    try:
        html = _build_instructor_payout_slip_html(b)
        pdf_bytes = get_pdf(html)
        pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

        view_url = f"/api/method/lms.lms.stride_lms.download_instructor_payout_slip?billing_name={b.name}"
        dl_url   = f"/api/method/lms.lms.stride_lms.download_instructor_payout_slip?billing_name={b.name}&as_attachment=1"

        return success({
            "billing_name": b.name,
            "filename": f"Payout_Slip_{b.name}.pdf",
            "pdf_base64": pdf_b64,
            "pdf_data_url": f"data:application/pdf;base64,{pdf_b64}",
            "view_url": view_url,
            "download_url": dl_url,
            "details": {
                "name": b.name,
                "instructor": b.instructor,
                "instructor_name": b.instructor_name or b.instructor,
                "payout_sheet": getattr(b, "payout_sheet", None),
                "billing_cycle": getattr(b, "billing_cycle", None) or "Monthly",
                "start_date": format_date(b.start_date) if getattr(b, "start_date", None) else "",
                "end_date": format_date(b.end_date) if getattr(b, "end_date", None) else "",
                "status": b.status,
                "gross_sales": flt(getattr(b, "gross_sales", 0) or 0),
                "platform_commission_rate": flt(getattr(b, "platform_commission_rate", 0) or 0),
                "platform_commission": flt(getattr(b, "platform_commission", 0) or 0),
                "gst_on_commission": flt(getattr(b, "gst_on_commission", 0) or 0),
                "refunds": flt(getattr(b, "refunds", 0) or 0),
                "net_earnings": flt(getattr(b, "net_earnings", 0) or 0),
                "tds_rate": flt(getattr(b, "tds_rate", 0) or 0),
                "tds_amount": flt(getattr(b, "tds_amount", 0) or 0),
                "net_payout": flt(getattr(b, "net_payout", 0) or 0),
                "paid_on": format_date(b.paid_on) if getattr(b, "paid_on", None) else "",
                "payment_mode": getattr(b, "payment_mode", None) or "NEFT",
                "payment_reference": getattr(b, "payment_reference", None) or ""
            }
        }, "Instructor payout slip data generated.")

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_instructor_payout_slip_data")
        return error(f"Failed to generate payout slip data: {str(e)}", 500)


# ═══════════════════════════════════════════════════════════════════════════
# INSTRUCTOR SALES & ENROLLMENT ANALYTICS REPORT
# ═══════════════════════════════════════════════════════════════════════════

def _resolve_period_dates(period, start_date, end_date):
    """Helper to convert preset period shortcuts into concrete start and end dates."""
    from frappe.utils import today, get_first_day, get_last_day, add_months, add_days
    t = today()
    if start_date or end_date:
        return start_date, end_date

    p = (period or "").lower().strip()
    if p == "this_month":
        return str(get_first_day(t)), str(t)
    elif p == "last_month":
        last_m = add_months(t, -1)
        return str(get_first_day(last_m)), str(get_last_day(last_m))
    elif p == "last_30_days":
        return str(add_days(t, -30)), str(t)
    elif p == "last_90_days":
        return str(add_days(t, -90)), str(t)
    elif p == "this_year":
        cur_year = t.split("-")[0] if isinstance(t, str) else str(t.year)
        return f"{cur_year}-01-01", str(t)
    return None, None


@frappe.whitelist(allow_guest=True)
def get_instructor_sales_report(
    instructor=None, start_date=None, end_date=None, period=None,
    course=None, item_type=None, search=None, page=1, page_size=20
):
    """
    Comprehensive Sales, Revenue, and Enrollment Report for Instructors.

    Provides:
      - KPI summary metrics (total revenue, count of courses/batches sold, students, AOV)
      - Dynamic filter options (courses and batches list)
      - Monthly aggregation trends (sales count, gross revenue, courses vs batches)
      - Course-level breakdown (sales count, revenue share %, unique students, avg price)
      - Paginated transaction records with student & payment details
    """
    from frappe.utils import format_date, format_time, flt, cint

    user = frappe.session.user
    if user == "Guest":
        if instructor:
            target = instructor
        else:
            return error("Authentication required.", 401)
    else:
        target = instructor if instructor else user
        if target != user:
            roles = frappe.get_roles(user)
            if not any(r in roles for r in ["Administrator", "System Manager", "Moderator", "LMS Admin"]):
                return error("Permission denied.", 403)

    resolved_start, resolved_end = _resolve_period_dates(period, start_date, end_date)
    course_names, batch_names = _get_instructor_courses_and_batches(target)

    # Fetch title & media maps
    course_titles = {}
    if course_names:
        for r in frappe.get_all("LMS Course", filters={"name": ["in", course_names]}, fields=["name", "title", "image"]):
            course_titles[r.name] = {"title": r.title, "image": r.image, "type": "course"}

    batch_titles = {}
    if batch_names:
        for r in frappe.get_all("LMS Batch", filters={"name": ["in", batch_names]}, fields=["name", "title"]):
            batch_titles[r.name] = {"title": r.title, "image": None, "type": "batch"}

    available_items = []
    for c_id, info in course_titles.items():
        available_items.append({"id": c_id, "title": info["title"], "type": "course"})
    for b_id, info in batch_titles.items():
        available_items.append({"id": b_id, "title": info["title"], "type": "batch"})

    target_courses = list(course_names)
    target_batches = list(batch_names)

    if course:
        if course in target_courses:
            target_courses = [course]
            target_batches = []
        elif course in target_batches:
            target_courses = []
            target_batches = [course]
        else:
            target_courses = []
            target_batches = []

    if item_type == "course":
        target_batches = []
    elif item_type == "batch":
        target_courses = []

    type_clauses = []
    values = {}
    if target_courses:
        type_clauses.append("(p.payment_for_document_type = 'LMS Course' AND p.payment_for_document IN %(tc)s)")
        values["tc"] = target_courses
    if target_batches:
        type_clauses.append("(p.payment_for_document_type = 'LMS Batch' AND p.payment_for_document IN %(tb)s)")
        values["tb"] = target_batches

    empty_response = {
        "instructor": target,
        "instructor_name": frappe.db.get_value("User", target, "full_name") or target,
        "filter_applied": {
            "period": period,
            "start_date": resolved_start,
            "end_date": resolved_end,
            "course": course,
            "item_type": item_type,
            "search": search
        },
        "available_items": available_items,
        "summary": {
            "total_orders": 0, "total_gross_sales": 0.0, "total_discount_given": 0.0,
            "total_courses_sold": 0, "total_batches_sold": 0, "unique_students": 0,
            "average_order_value": 0.0, "top_performing_course": "None"
        },
        "monthly_breakdown": [],
        "course_wise_breakdown": [],
        "transactions": [],
        "pagination": {"total": 0, "page": 1, "page_size": cint(page_size or 20), "total_pages": 0}
    }

    if not type_clauses:
        return success(empty_response, "No courses or batches found for instructor.")

    conditions = ["p.payment_received = 1", f"({' OR '.join(type_clauses)})"]

    if resolved_start:
        conditions.append("DATE(p.creation) >= %(s)s")
        values["s"] = resolved_start
    if resolved_end:
        conditions.append("DATE(p.creation) <= %(e)s")
        values["e"] = resolved_end
    if search:
        conditions.append("(p.name LIKE %(q)s OR p.member LIKE %(q)s OR p.billing_name LIKE %(q)s OR p.payment_id LIKE %(q)s OR p.payment_for_document LIKE %(q)s)")
        values["q"] = f"%{search}%"

    where_str = " AND ".join(conditions)

    all_txns = frappe.db.sql(f"""
        SELECT p.name, p.payment_id, p.order_id, p.member, p.billing_name,
               p.payment_for_document_type, p.payment_for_document,
               p.amount, p.original_amount, p.discount_amount, p.coupon_code,
               p.currency, p.creation
        FROM `tabLMS Payment` p
        WHERE {where_str}
        ORDER BY p.creation DESC
    """, values, as_dict=True)

    formatted_txns = []
    total_gross = 0.0
    total_disc  = 0.0
    courses_sold = 0
    batches_sold = 0
    students_set = set()
    course_stats = {}
    monthly_stats = {}

    for t in all_txns:
        doc_type = t.payment_for_document_type
        doc_name = t.payment_for_document
        is_course = doc_type == "LMS Course"
        info = course_titles.get(doc_name, {}) if is_course else batch_titles.get(doc_name, {})
        title = info.get("title") or doc_name

        amt = flt(t.amount or 0)
        disc = flt(t.discount_amount or 0)
        orig = flt(t.original_amount or amt)

        total_gross += amt
        total_disc  += disc
        if is_course:
            courses_sold += 1
        else:
            batches_sold += 1

        students_set.add(t.member)

        # Course stats
        if doc_name not in course_stats:
            course_stats[doc_name] = {
                "item_id": doc_name,
                "item_title": title,
                "item_type": "course" if is_course else "batch",
                "item_image": info.get("image"),
                "sales_count": 0,
                "gross_revenue": 0.0,
                "students": set()
            }
        course_stats[doc_name]["sales_count"] += 1
        course_stats[doc_name]["gross_revenue"] += amt
        course_stats[doc_name]["students"].add(t.member)

        # Monthly stats
        dt = t.creation
        m_key = dt.strftime("%Y-%m")
        m_label = dt.strftime("%b %Y")
        if m_key not in monthly_stats:
            monthly_stats[m_key] = {
                "month_key": m_key,
                "month_label": m_label,
                "sales_count": 0,
                "gross_revenue": 0.0,
                "courses_sold": 0,
                "batches_sold": 0,
                "students": set()
            }
        monthly_stats[m_key]["sales_count"] += 1
        monthly_stats[m_key]["gross_revenue"] += amt
        if is_course:
            monthly_stats[m_key]["courses_sold"] += 1
        else:
            monthly_stats[m_key]["batches_sold"] += 1
        monthly_stats[m_key]["students"].add(t.member)

        formatted_txns.append({
            "name": t.name,
            "payment_id": t.payment_id or "N/A",
            "order_id": t.order_id or "N/A",
            "student_name": t.billing_name or t.member,
            "student_email": t.member,
            "item_type": "course" if is_course else "batch",
            "item_id": doc_name,
            "item_title": title,
            "amount": amt,
            "original_amount": orig,
            "discount_amount": disc,
            "coupon_code": t.coupon_code,
            "currency": t.currency or "INR",
            "date": format_date(dt),
            "time": format_time(dt),
            "created_at": str(dt)
        })

    course_list = []
    for cid, cdata in course_stats.items():
        c_sales = cdata["gross_revenue"]
        pct = round((c_sales / total_gross) * 100, 1) if total_gross > 0 else 0
        avg = round(c_sales / cdata["sales_count"], 2) if cdata["sales_count"] > 0 else 0
        course_list.append({
            "item_id": cdata["item_id"],
            "item_title": cdata["item_title"],
            "item_type": cdata["item_type"],
            "item_image": cdata["item_image"],
            "sales_count": cdata["sales_count"],
            "gross_revenue": cdata["gross_revenue"],
            "unique_students": len(cdata["students"]),
            "percentage_of_total": pct,
            "average_price": avg
        })
    course_list.sort(key=lambda x: x["gross_revenue"], reverse=True)

    monthly_list = []
    for m_key in sorted(monthly_stats.keys()):
        mdata = monthly_stats[m_key]
        monthly_list.append({
            "month_key": mdata["month_key"],
            "month_label": mdata["month_label"],
            "sales_count": mdata["sales_count"],
            "gross_revenue": mdata["gross_revenue"],
            "courses_sold": mdata["courses_sold"],
            "batches_sold": mdata["batches_sold"],
            "unique_students": len(mdata["students"])
        })

    total_orders = len(formatted_txns)
    aov = round(total_gross / total_orders, 2) if total_orders > 0 else 0
    top_course = course_list[0]["item_title"] if course_list else "None"

    # Pagination
    page = max(1, cint(page or 1))
    page_size = cint(page_size or 20)
    total_pages = max(1, -(-total_orders // page_size)) if page_size > 0 else 1

    paginated_txns = formatted_txns
    if page_size > 0:
        offset = (page - 1) * page_size
        paginated_txns = formatted_txns[offset:offset + page_size]

    return success({
        "instructor": target,
        "instructor_name": frappe.db.get_value("User", target, "full_name") or target,
        "filter_applied": {
            "period": period,
            "start_date": resolved_start,
            "end_date": resolved_end,
            "course": course,
            "item_type": item_type,
            "search": search
        },
        "available_items": available_items,
        "summary": {
            "total_orders": total_orders,
            "total_gross_sales": total_gross,
            "total_discount_given": total_disc,
            "total_courses_sold": courses_sold,
            "total_batches_sold": batches_sold,
            "unique_students": len(students_set),
            "average_order_value": aov,
            "top_performing_course": top_course
        },
        "monthly_breakdown": monthly_list,
        "course_wise_breakdown": course_list,
        "transactions": paginated_txns,
        "pagination": {
            "total": total_orders,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages
        }
    }, "Sales report generated.")


@frappe.whitelist(allow_guest=True)
def export_instructor_sales_report_csv(
    instructor=None, start_date=None, end_date=None, period=None,
    course=None, item_type=None, search=None
):
    """
    Export full sales report as a downloadable CSV spreadsheet.
    """
    import csv
    import io
    from frappe.utils import today

    res = get_instructor_sales_report(
        instructor=instructor,
        start_date=start_date,
        end_date=end_date,
        period=period,
        course=course,
        item_type=item_type,
        search=search,
        page=1,
        page_size=0
    )

    if res.get("status") != 200:
        return res

    report_data = res.get("data", {})
    txns = report_data.get("transactions", [])
    target = report_data.get("instructor") or "instructor"

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Transaction ID", "Payment Gateway ID", "Order ID", "Date", "Time",
        "Student Name", "Student Email", "Type", "Item ID", "Course / Batch Title",
        "Amount Paid", "List Price", "Discount", "Coupon Code", "Currency"
    ])

    for t in txns:
        writer.writerow([
            t.get("name", ""),
            t.get("payment_id", ""),
            t.get("order_id", ""),
            t.get("date", ""),
            t.get("time", ""),
            t.get("student_name", ""),
            t.get("student_email", ""),
            t.get("item_type", ""),
            t.get("item_id", ""),
            t.get("item_title", ""),
            f"{t.get('amount', 0):.2f}",
            f"{t.get('original_amount', 0):.2f}",
            f"{t.get('discount_amount', 0):.2f}",
            t.get("coupon_code") or "",
            t.get("currency", "INR")
        ])

    csv_content = output.getvalue()
    filename = f"Sales_Report_{target}_{today()}.csv"

    frappe.response.filecontent = csv_content
    frappe.response.filename = filename
    frappe.response.type = "download"
    frappe.response.display_content_as = "attachment"
    frappe.response.content_type = "text/csv; charset=utf-8"
