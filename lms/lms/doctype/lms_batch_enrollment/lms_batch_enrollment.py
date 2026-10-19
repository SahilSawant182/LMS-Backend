# Copyright (c) 2025, Frappe and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import make_notification_logs
from frappe.email.doctype.email_template.email_template import get_email_template
from frappe.model.document import Document
from frappe.query_builder import Bracket
from pypika.terms import LiteralValue

from lms.lms.doctype.lms_enrollment.lms_enrollment import validate_identity_unchanged
from lms.lms.permissions import authored_batch_condition, can_author_batch, is_site_administrator
from lms.lms.utils import has_moderator_role

# Roles that keep today's blanket access: every row, every ptype.
UNSCOPED_ROLES = ("Moderator", "Batch Evaluator")

from lms.lms.utils import get_lms_route


class LMSBatchEnrollment(Document):
	def after_insert(self):
		send_confirmation_email(self)
		from lms.lms.doctype.lms_live_class.lms_live_class import add_learner_to_live_classes

		add_learner_to_live_classes(self.batch)
		
		self.notify_instructors_of_new_batch_enrollment()

	def on_trash(self):
		self.notify_instructors_of_dropout()

	def validate(self):
		validate_identity_unchanged(self, ("batch", "member"))
		self.validate_owner()
		self.validate_duplicate_members()
		self.validate_payment()
		self.validate_self_enrollment()
		self.validate_seat_availability()
		self.validate_course_enrollment()

	def validate_owner(self):
		if self.owner == self.member:
			return

		roles = frappe.get_roles()
		if "Moderator" in roles or "Batch Evaluator" in roles:
			return
		# Scoped, unlike the two roles above: a Course Creator may only enrol
		# members into a batch they are actually tagged an instructor/evaluator on.
		if can_author_batch(self.batch):
			return

		frappe.throw(
			_("You must be a Moderator, Batch Evaluator, or this batch's instructor to enroll users.")
		)

	def validate_payment(self):
		paid_batch = frappe.db.get_value("LMS Batch", self.batch, "paid_batch")
		if paid_batch and not self.can_skip_payment():
			payment = frappe.db.exists(
				"LMS Payment",
				{
					"payment_for_document_type": "LMS Batch",
					"payment_for_document": self.batch,
					"member": self.member,
					"payment_received": True,
				},
			)
			if not payment:
				frappe.throw(_("Payment is required to enroll in this batch."))
			else:
				self.payment = payment

	def validate_self_enrollment(self):
		batch_details = frappe.db.get_value(
			"LMS Batch", self.batch, ["allow_self_enrollment", "paid_batch"], as_dict=True
		)
		if batch_details.paid_batch:
			return
		if not batch_details.allow_self_enrollment and not self.is_admin():
			frappe.throw(_("Enrollment in this batch is restricted. Please contact the Administrator."))

	def is_admin(self):
		roles = frappe.get_roles(frappe.session.user)
		return "Course Creator" in roles or "Moderator" in roles or "Batch Evaluator" in roles

	def can_skip_payment(self):
		"""Only a site admin or Moderator enrolls themselves without paying. The
		batch's tagged instructors and evaluators may also enroll others free."""
		if self.owner != self.member:
			return can_author_batch(self.batch)
		return is_site_administrator() or bool(has_moderator_role())

	def validate_duplicate_members(self):
		# Lock the batch row for the rest of this transaction before reading. The
		# check below is a read of a row a concurrent request has not inserted
		# yet, so without the lock both requests see "absent" and both insert —
		# and a duplicate row also consumes a seat in validate_seat_availability,
		# which turns a double-click into "no seats available" for someone else.
		# Same shape as the payment and coupon locks in lms/lms/utils.py.
		frappe.db.get_value("LMS Batch", self.batch, "name", for_update=True)

		if frappe.db.exists(
			"LMS Batch Enrollment",
			{"batch": self.batch, "member": self.member, "name": ["!=", self.name]},
		):
			frappe.throw(_("Member already enrolled in this batch"))

	def validate_seat_availability(self):
		seat_count = frappe.db.get_value("LMS Batch", self.batch, "seat_count")
		enrolled_count = frappe.db.count("LMS Batch Enrollment", {"batch": self.batch})
		if seat_count and enrolled_count >= seat_count:
			frappe.throw(_("There are no seats available in this batch."))

	def validate_course_enrollment(self):
		courses = frappe.get_all("Batch Course", filters={"parent": self.batch}, fields=["course"])

		for course in courses:
			# Same reasoning as validate_duplicate_members, one level down: without
			# the lock, two batches sharing a course can both read "absent" for the
			# same member and the loser's inner insert throws, failing an enrolment
			# that should have skipped. Batch row first, then course row, in that
			# order everywhere — the reverse order exists nowhere, so no cycle.
			frappe.db.get_value("LMS Course", course.course, "name", for_update=True)

			if not frappe.db.exists(
				"LMS Enrollment",
				{"course": course.course, "member": self.member},
			):
				enrollment = frappe.new_doc("LMS Enrollment")
				enrollment.course = course.course
				enrollment.member = self.member
				enrollment.enrollment_from_batch = self.batch
				enrollment.save()


	def notify_instructors_of_new_batch_enrollment(self):
		"""N10 – System notification to batch instructors when a student enrolls."""
		instructors = frappe.get_all(
			"Course Instructor",
			{"parent": self.batch, "parenttype": "LMS Batch"},
			pluck="instructor",
		)
		if not instructors:
			return

		student_name = frappe.db.get_value("User", self.member, "full_name") or self.member
		batch_title = frappe.db.get_value("LMS Batch", self.batch, "title") or self.batch
		link = get_lms_route(f"batches/{self.batch}")

		notification = frappe._dict(
			{
				"subject": _("{0} enrolled in your batch {1}").format(
					frappe.bold(student_name), frappe.bold(batch_title)
				),
				"email_content": _(
					"{0} has just joined your batch '{1}'. Your class size has grown!"
				).format(student_name, batch_title),
				"document_type": "LMS Batch Enrollment",
				"document_name": self.name,
				"from_user": self.member,
				"type": "Alert",
				"link": link,
			}
		)
		try:
			make_notification_logs(notification, instructors)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "LMS: Batch enrollment instructor notification failed")

	def notify_instructors_of_dropout(self):
		"""N11 – System notification to batch instructors when a student drops from the batch."""
		instructors = frappe.get_all(
			"Course Instructor",
			{"parent": self.batch, "parenttype": "LMS Batch"},
			pluck="instructor",
		)
		if not instructors:
			return

		student_name = frappe.db.get_value("User", self.member, "full_name") or self.member
		batch_title = frappe.db.get_value("LMS Batch", self.batch, "title") or self.batch
		link = get_lms_route(f"batches/{self.batch}")

		notification = frappe._dict(
			{
				"subject": _("{0} has dropped from your batch {1}").format(
					frappe.bold(student_name), frappe.bold(batch_title)
				),
				"email_content": _(
					"{0} has withdrawn from your batch '{1}'. Please update your headcount accordingly."
				).format(student_name, batch_title),
				"document_type": "LMS Batch",
				"document_name": self.batch,
				"from_user": self.member,
				"type": "Alert",
				"link": link,
			}
		)
		try:
			make_notification_logs(notification, instructors)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "LMS: Batch dropout instructor notification failed")


@frappe.whitelist()
def send_confirmation_email(doc: Document | str):
	if isinstance(doc, str):
		name = frappe.parse_json(doc).get("name")
		doc = frappe.get_doc("LMS Batch Enrollment", name)

	roles = frappe.get_roles()
	is_admin = "Moderator" in roles or "Batch Evaluator" in roles or can_author_batch(doc.batch)
	is_member = doc.member == frappe.session.user

	if not is_member and not is_admin:
		frappe.throw(
			_("You do not have permission to send confirmation emails for this enrollment."),
			frappe.PermissionError,
		)

	if not doc.confirmation_email_sent:
		outgoing_email_account = frappe.get_cached_value(
			"Email Account", {"default_outgoing": 1, "enable_outgoing": 1}, "name"
		)
		if not doc.confirmation_email_sent and (outgoing_email_account or frappe.conf.get("mail_login")):
			send_mail(doc)
			frappe.db.set_value(doc.doctype, doc.name, "confirmation_email_sent", 1)


def send_mail(doc):
	batch = frappe.db.get_value(
		"LMS Batch",
		doc.batch,
		[
			"name",
			"title",
			"start_date",
			"start_time",
			"medium",
			"confirmation_email_template",
		],
		as_dict=1,
	)

	subject = _("Enrollment Confirmation for {0}").format(batch.title)
	template = "batch_confirmation"
	custom_template = batch.confirmation_email_template or frappe.db.get_single_value(
		"LMS Settings", "batch_confirmation_template"
	)

	args = {
		"title": batch.title,
		"student_name": doc.member_name,
		"start_time": batch.start_time,
		"start_date": batch.start_date,
		"medium": batch.medium,
		"name": batch.name,
	}

	if custom_template:
		email_template = get_email_template(custom_template, args)
		subject = email_template.get("subject")
		content = email_template.get("message")

	frappe.sendmail(
		recipients=doc.member,
		subject=subject,
		template=template if not custom_template else None,
		content=content if custom_template else None,
		args=args,
		header=[_(batch.title), "green"],
		retry=3,
	)


<<<<<<< Updated upstream
def has_permission(doc, ptype="read", user=None):
	"""A Course Creator's unconditional DocPerm row narrowed to the batches they
	author. Moderator and Batch Evaluator keep today's blanket access; an
	enrolled member reads their own row either way."""
	user = user or frappe.session.user
	roles = frappe.get_roles(user)
	if is_site_administrator(user) or any(role in roles for role in UNSCOPED_ROLES):
		return True

	if doc.is_new():
		# Mirrors validate_owner(): self-enrollment needs no batch authorship.
		# Whether this batch actually allows it is validate()'s decision.
		if doc.get("member") == user:
			return True
		return can_author_batch(doc.get("batch"), user=user)

	stored = frappe.db.get_value(doc.doctype, doc.name, ["batch", "member"], as_dict=True)
	if not stored:
		return False

	if ptype in ("read", "select", "print") and stored.member == user and doc.get("member") == user:
		return True

	# Both the stored and the submitted batch, or a save could move the row out
	# of its owner's reach by repointing it at a batch they don't author.
	batches = {stored.batch, doc.get("batch")} - {None}
	return all(can_author_batch(batch, user=user) for batch in batches)


def get_permission_query_conditions(user=None):
	"""List-read counterpart of :func:`has_permission`, as SQL."""
	user = user or frappe.session.user
	roles = frappe.get_roles(user)
	if is_site_administrator(user) or any(role in roles for role in UNSCOPED_ROLES):
		return ""

	enrollment = frappe.qb.DocType("LMS Batch Enrollment")
	member = LiteralValue(frappe.db.escape(user))
	condition = Bracket((enrollment.member == member) | authored_batch_condition(enrollment.batch, user))
	return condition.get_sql(with_namespace=True, quote_char="`" if frappe.db.db_type == "mariadb" else '"')
=======


@frappe.whitelist()
def enroll_student(member, batch, payment=None, source=None):
    """
    Enroll a student/member into an LMS Batch.

    API:
    /api/method/stridenex_app.api_stridenex_app.lms.enroll_student

    Method:
    POST

    Example body:
    {
        "member": "student@example.com",
        "batch": "BATCH-0001",
        "payment": "PAY-0001",
        "source": "SRC-0001"
    }
    """

    try:
        if not member:
            return {
                "success": False,
                "message": "Member is required"
            }

        if not batch:
            return {
                "success": False,
                "message": "Batch is required"
            }

        # Check User exists
        if not frappe.db.exists("User", member):
            return {
                "success": False,
                "message": f"User {member} does not exist"
            }

        # Check Batch exists
        if not frappe.db.exists("LMS Batch", batch):
            return {
                "success": False,
                "message": f"LMS Batch {batch} does not exist"
            }

        # Check duplicate enrollment
        existing = frappe.db.exists(
            "LMS Batch Enrollment",
            {
                "member": member,
                "batch": batch
            }
        )

        if existing:
            return {
                "success": False,
                "message": "Student is already enrolled in this batch",
                "enrollment": existing
            }

        # Create enrollment
        enrollment = frappe.get_doc({
            "doctype": "LMS Batch Enrollment",
            "member": member,
            "batch": batch,
            "payment": payment,
            "source": source
        })

        enrollment.insert(ignore_permissions=True)
        frappe.db.commit()

        return {
            "success": True,
            "message": "Student enrolled successfully",
            "data": {
                "name": enrollment.name,
                "member": enrollment.member,
                "member_name": enrollment.member_name,
                "member_username": enrollment.member_username,
                "member_image": enrollment.member_image,
                "batch": enrollment.batch,
                "payment": enrollment.payment,
                "source": enrollment.source,
                "confirmation_email_sent": enrollment.confirmation_email_sent,
                "creation": enrollment.creation
            }
        }

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "LMS Student Enrollment API Error"
        )

        frappe.db.rollback()

        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist()
def get_enrolled_students(batch=None, member=None, txt="", limit=20, start=0):
    """
    Get enrolled students.

    API:
    /api/method/stridenex_app.api_stridenex_app.lms.get_enrolled_students

    Examples:

    All enrollments:
    ?limit=20&start=0

    Students of a batch:
    ?batch=BATCH-0001

    Specific student:
    ?member=student@example.com

    Search:
    ?batch=BATCH-0001&txt=John
    """

    try:
        limit = min(int(limit), 100)
        start = int(start)

        filters = {}

        if batch:
            if not frappe.db.exists("LMS Batch", batch):
                return {
                    "success": False,
                    "message": f"LMS Batch {batch} does not exist"
                }

            filters["batch"] = batch

        if member:
            filters["member"] = member

        conditions = []
        values = {
            "limit": limit,
            "start": start
        }

        if batch:
            conditions.append("e.batch = %(batch)s")
            values["batch"] = batch

        if member:
            conditions.append("e.member = %(member)s")
            values["member"] = member

        if txt:
            conditions.append("""
                (
                    e.member LIKE %(txt)s
                    OR e.member_name LIKE %(txt)s
                    OR e.member_username LIKE %(txt)s
                )
            """)
            values["txt"] = f"%{txt}%"

        where_clause = ""

        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        students = frappe.db.sql(
            f"""
            SELECT
                e.name,
                e.member,
                e.member_name,
                e.member_username,
                e.member_image,
                e.batch,
                e.payment,
                e.source,
                e.confirmation_email_sent,
                e.creation
            FROM `tabLMS Batch Enrollment` e
            {where_clause}
            ORDER BY e.creation DESC
            LIMIT %(start)s, %(limit)s
            """,
            values,
            as_dict=True
        )

        # Total count
        total = frappe.db.sql(
            f"""
            SELECT COUNT(*) AS total
            FROM `tabLMS Batch Enrollment` e
            {where_clause}
            """,
            values,
            as_dict=True
        )[0].total

        return {
            "success": True,
            "data": students,
            "pagination": {
                "total": total,
                "limit": limit,
                "start": start,
                "has_more": (start + len(students)) < total
            }
        }

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "LMS Enrolled Students API Error"
        )

        return {
            "success": False,
            "message": str(e)
        }

>>>>>>> Stashed changes
