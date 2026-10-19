# Copyright (c) 2021, FOSS United and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import make_notification_logs
from frappe.model.document import Document
from frappe.utils import cint

from lms.lms.utils import get_lms_route


class LMSQuizSubmission(Document):
	def validate(self):
		self.validate_if_max_attempts_exceeded()
		self.sanitize_result_html()
		self.validate_marks()
		self.set_percentage()

	def after_insert(self):
		"""N30 – Notify instructor if this submission exhausts all allowed attempts."""
		self.notify_instructor_of_exhausted_attempts()

	def on_update(self):
		self.notify_member()

	def validate_if_max_attempts_exceeded(self):
		max_attempts = frappe.db.get_value("LMS Quiz", self.quiz, ["max_attempts"])
		if max_attempts == 0:
			return

		current_user_submission_count = frappe.db.count(
			self.doctype, filters={"quiz": self.quiz, "member": self.member}
		)
		if current_user_submission_count >= max_attempts:
			frappe.throw(
				_("You have exceeded the maximum number of attempts ({0}) for this quiz").format(
					max_attempts
				),
				MaximumAttemptsExceededError,
			)

	def validate_marks(self):
		self.score = 0
		for row in self.result:
			if cint(row.marks) > cint(row.marks_out_of):
				frappe.throw(
					_(
						"Marks for question number {0} cannot be greater than the marks allotted for that question."
					).format(row.idx)
				)
			else:
				self.score += cint(row.marks)

	def set_percentage(self):
		if self.score and self.score_out_of:
			# Floored at zero, or negative marking throws the whole submission away.
			self.percentage = max(0, (self.score / self.score_out_of) * 100)

	def notify_member(self):
		if self.score != 0 and self.has_value_changed("score"):
			notification = frappe._dict(
				{
					"subject": _("You have got a score of {0} for the quiz {1}").format(
						(frappe.bold(self.score)), frappe.bold(self.quiz_title)
					),
					"email_content": _(
						"There has been an update on your submission. You have got a score of {0} for the quiz {1}"
					).format(frappe.bold(self.score), frappe.bold(self.quiz_title)),
					"document_type": self.doctype,
					"document_name": self.name,
					"for_user": self.member,
					"from_user": frappe.session.user,
					"type": "Alert",
					"link": "",
				}
			)

			make_notification_logs(notification, [self.member])

			# N28 – First-attempt pass celebration notification
			self.notify_first_attempt_pass()

	def notify_first_attempt_pass(self):
		"""N28 – Positive in-app alert when the student passes a quiz on their very first attempt."""
		passing_percentage = frappe.db.get_value("LMS Quiz", self.quiz, "passing_percentage") or 0
		if not passing_percentage:
			return

		if (self.percentage or 0) < cint(passing_percentage):
			return  # did not pass

		# Check this is the first submission for this quiz by this member
		submission_count = frappe.db.count(
			self.doctype, {"quiz": self.quiz, "member": self.member}
		)
		if submission_count != 1:
			return  # not first attempt

		notification = frappe._dict(
			{
				"subject": _("🎉 You passed {0} on your first try! Score: {1}/{2}").format(
					frappe.bold(self.quiz_title), self.score, self.score_out_of
				),
				"email_content": _(
					"Great job! You scored {0} out of {1} on '{2}' on your first attempt — keep it up!"
				).format(self.score, self.score_out_of, self.quiz_title),
				"document_type": self.doctype,
				"document_name": self.name,
				"from_user": frappe.session.user,
				"type": "Alert",
				"link": "",
			}
		)
		try:
			make_notification_logs(notification, [self.member])
		except Exception:
			frappe.log_error(frappe.get_traceback(), "LMS: First-attempt pass notification failed")

	def notify_instructor_of_exhausted_attempts(self):
		"""N30 – Notify course instructors when a student has used all allowed quiz attempts."""
		max_attempts = frappe.db.get_value("LMS Quiz", self.quiz, "max_attempts") or 0
		if not max_attempts:
			return  # unlimited attempts, no need to notify

		attempt_count = frappe.db.count(
			self.doctype, {"quiz": self.quiz, "member": self.member}
		)
		if attempt_count < cint(max_attempts):
			return  # still has attempts left

		# Find instructors for the course linked to this quiz
		course = frappe.db.get_value("LMS Quiz", self.quiz, "course")
		if not course:
			return

		instructors = frappe.get_all(
			"Course Instructor",
			{"parent": course, "parenttype": "LMS Course"},
			pluck="instructor",
		)
		if not instructors:
			return

		student_name = frappe.db.get_value("User", self.member, "full_name") or self.member
		notification = frappe._dict(
			{
				"subject": _("⚠️ {0} has used all {1} attempts for quiz {2}").format(
					frappe.bold(student_name), max_attempts, frappe.bold(self.quiz_title)
				),
				"email_content": _(
					"{0} has exhausted all {1} allowed attempts for the quiz '{2}'. "
					"You may want to reset their attempts or provide additional support."
				).format(student_name, max_attempts, self.quiz_title),
				"document_type": "LMS Quiz Submission",
				"document_name": self.name,
				"from_user": self.member,
				"type": "Alert",
				"link": "",
			}
		)
		try:
			make_notification_logs(notification, instructors)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "LMS: Quiz exhausted attempts instructor notification failed")



class MaximumAttemptsExceededError(frappe.DuplicateEntryError):
	pass
