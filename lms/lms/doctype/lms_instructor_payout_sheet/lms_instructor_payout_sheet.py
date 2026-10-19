import frappe
from frappe.model.document import Document

class LMSInstructorPayoutSheet(Document):
    def validate(self):
        self.title = f"Instructor Payout: {self.start_date} to {self.end_date} ({self.billing_cycle})"

class LmsInstructorPayoutSheet(LMSInstructorPayoutSheet):
    pass
