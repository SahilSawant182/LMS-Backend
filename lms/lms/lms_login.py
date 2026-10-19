


import frappe 

from frappe.utils.password import update_password
import random
import requests
from urllib.parse import quote
from lms.lms.utils import (
    gen_response,
    exception_handel,generate_key
)
from frappe.auth import LoginManager
import string
import random
from urllib.parse import quote
import frappe
from frappe import _
from frappe.utils import now_datetime, add_to_date



@frappe.whitelist(allow_guest=True)
def signup():

    if frappe.request.method != "POST":
        return gen_response(400, "Only POST allowed", {"success": False})

    try:
        data = frappe.request.get_json()

        first_name = data.get("first_name")
        last_name = data.get("last_name")
        email = data.get("email")
        password = data.get("password")
        roles = data.get("role")
        partner_referal = data.get("partner_referal")

        if not roles:
            return gen_response(
                400,
                "Role selection required",
                {"success": False}
            )

        if not all([first_name, last_name, email, password]):
            return gen_response(
                400,
                "All fields are required",
                {"success": False}
            )

        if frappe.db.exists("User", email):
            return gen_response(
                400,
                "User already exists",
                {"success": False}
            )

        # -----------------------------------
        # Detect selected role
        # -----------------------------------

        selected_role = None

        for role_item in roles:
            for key, value in role_item.items():
                if value in [1, "1", True, "true", "True"]:
                    selected_role = key
                    break

            if selected_role:
                break

        if not selected_role:
            return gen_response(
                400,
                "Role not selected",
                {"success": False}
            )

        # -----------------------------------
        # Map UI role to system role
        # -----------------------------------

        role_map = {
            "student": "Student",
            "instructor": "Instructor",
            "mentor": "Mentor",
            "industry": "Industry base",
            "admin": "Lms Admin"
        }

        frappe_role = role_map.get(selected_role)

        if not frappe_role:
            return gen_response(
                400,
                "Invalid role selected",
                {"success": False}
            )

        

        # -----------------------------------
        # Create User
        # -----------------------------------

        user = frappe.get_doc({
            "doctype": "User",
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "enabled": 1,
            "new_password": password,
            "user_type": "Website User",

          
        })

        user.flags.no_welcome_mail = True
        user.is_onboarded = False

        user.insert(ignore_permissions=True)
        update_password(user.name, password)
        user.add_roles(frappe_role)

        # -----------------------------------
        # Commit
        # -----------------------------------

        frappe.db.commit()

        return gen_response(
            200,
            "User created successfully",
            {
                "success": True,
                "role": frappe_role,
               
            }
        )

    except Exception:
        frappe.db.rollback()

        frappe.log_error(
            frappe.get_traceback(),
            "Signup Error"
        )

        return gen_response(
            500,
            "Something went wrong",
            frappe.get_traceback()
        )



@frappe.whitelist(allow_guest=True)
def login(usr, pwd):
    try:
        login_manager = LoginManager()
        login_manager.authenticate(usr, pwd)
        login_manager.post_login()

        if frappe.response["message"] == "Logged In":

            user = login_manager.user
          
            # Get user roles
            roles = frappe.get_roles(user)

            # Remove default roles if needed
            ignore_roles = ["All", "Guest"]
            roles = [r for r in roles if r not in ignore_roles]
           
            user_image = frappe.db.get_value("User", user, "user_image")

            frappe.response["user"] = user
            frappe.response["roles"] = roles
         
            frappe.response["user_image"] = user_image
            frappe.response["key_details"] = generate_key(user)

        gen_response(200, frappe.response["message"])

    except frappe.AuthenticationError:
        gen_response(500, frappe.response["message"])

    except Exception as e:
        return exception_handel(e)


@frappe.whitelist(allow_guest=True)
def forgot_password():

    if frappe.request.method != "POST":
        return gen_response(
            400,
            "Only POST allowed",
            {"success": False}
        )

    try:
        data = frappe.request.get_json() or {}

        email = data.get("email")

        if not email:
            return gen_response(
                400,
                "Email is required",
                {"success": False}
            )

        # -----------------------------------
        # CHECK USER
        # -----------------------------------

        user = frappe.db.get_value(
            "User",
            {"email": email},
            ["name", "enabled", "first_name"],
            as_dict=True
        )

        if not user:
            return gen_response(
                404,
                "User not found",
                {"success": False}
            )

        if not user.enabled:
            return gen_response(
                400,
                "User account is disabled",
                {"success": False}
            )

        # -----------------------------------
        # GENERATE RESET KEY
        # -----------------------------------

        reset_key = frappe.generate_hash(length=32)

        # Frappe stores the SHA256 hash,
        # not the original key
        hashed_key = frappe.utils.sha256_hash(reset_key)

        # -----------------------------------
        # SAVE RESET KEY
        # -----------------------------------

        frappe.db.set_value(
            "User",
            user.name,
            {
                "reset_password_key": hashed_key,
                "last_reset_password_key_generated_on": frappe.utils.now_datetime()
            }
        )

        frappe.db.commit()

        # -----------------------------------
        # CREATE RESET LINK
        # -----------------------------------

        reset_url = (
            frappe.utils.get_url()
            + "/update-password?key="
            + reset_key
        )

        # -----------------------------------
        # SEND EMAIL
        # -----------------------------------

        frappe.sendmail(
            recipients=[email],
            subject="Reset Your Stridenex Password",
            message=f"""
                <div style="font-family: Arial, sans-serif;">

                    <h2>Password Reset</h2>

                    <p>
                        Hello {user.first_name or ''},
                    </p>

                    <p>
                        We received a request to reset your
                        Stridenex account password.
                    </p>

                    <p>
                        Click the button below to create a new password:
                    </p>

                    <p>
                        <a href="{reset_url}"
                           style="
                               display:inline-block;
                               padding:12px 24px;
                               background:#1677ff;
                               color:#ffffff;
                               text-decoration:none;
                               border-radius:6px;
                               font-weight:bold;
                           ">
                            Reset Password
                        </a>
                    </p>

                    <p>
                        Or copy and paste this link into your browser:
                    </p>

                    <p>
                        <a href="{reset_url}">
                            {reset_url}
                        </a>
                    </p>

                    <p>
                        If you did not request a password reset,
                        please ignore this email.
                    </p>

                </div>
            """
        )

        return gen_response(
            200,
            "Password reset link sent successfully",
            {
                "success": True
            }
        )

    except Exception as e:

        frappe.log_error(
            frappe.get_traceback(),
            "Forgot Password Error"
        )

        return gen_response(
            500,
            str(e),
            {
                "success": False
            }
        )


@frappe.whitelist()
def logout():
    try:
        frappe.local.login_manager.logout()
        return gen_response(200, "Logged out successfully.")
    except Exception as e:
        return exception_handel(e)



@frappe.whitelist(allow_guest=True)
def send_mobile_otp(mobile_no=None):

    if not mobile_no:
        return gen_response(
            400,
            "Mobile number is required"
        )

    # -----------------------------------
    # GENERATE OTP
    # -----------------------------------

    otp = str(random.randint(100000, 999999))

    expiry_time = add_to_date(
        now_datetime(),
        minutes=10
    )

    # -----------------------------------
    # SAVE OTP RECORD
    # -----------------------------------

    try:

        existing_doc = frappe.db.exists(
            "Validate Mobile OTP",
            {"mobile_no": mobile_no}
        )

        if existing_doc:

            otp_doc = frappe.get_doc(
                "Validate Mobile OTP",
                existing_doc
            )

            otp_doc.otp = otp
            otp_doc.expiry_time = expiry_time

            otp_doc.save(ignore_permissions=True)

        else:

            otp_doc = frappe.get_doc({
                "doctype": "Validate Mobile OTP",
                "mobile_no": mobile_no,
                "otp": otp,
                "expiry_time": expiry_time
            })

            otp_doc.insert(ignore_permissions=True)

        # IMPORTANT
        frappe.db.commit()

    except Exception as e:

        frappe.log_error(
            frappe.get_traceback(),
            "OTP Save Failed"
        )

        return gen_response(
            500,
            f"OTP save failed: {str(e)}"
        )

    # -----------------------------------
    # SEND SMS
    # -----------------------------------

    try:

        message = quote(
            f"Your Stridenex account verification OTP is {otp} "
            f".Valid for 10 minutes.Do not share this OTP."
        )

        sms_url = (
            "http://vas.mobilogi.com/api.php"
            f"?username=strdnx"
            f"&password=pass123"
            f"&route=1"
            f"&sender=STRDNX"
            f"&mobile[]={mobile_no}"
            f"&message[]={message}"
            f"&templateid=1007550961776829496"
        )

        response = requests.get(
            sms_url,
            timeout=15
        )

        response_text = response.text.strip()

    except Exception as e:

        frappe.log_error(
            frappe.get_traceback(),
            "OTP SMS Failed"
        )

        return gen_response(
            500,
            f"SMS failed: {str(e)}"
        )

    return gen_response(
        200,
        "OTP sent successfully",
        {
            "mobile_no": mobile_no,
            "sms_response": response_text
        }
    )
    
    

@frappe.whitelist(allow_guest=True)
def validate_mobile_otp(mobile_no=None, otp=None,email=None):
    if not mobile_no:
        return gen_response(400, "Mobile number is required",{"success": False})

    if not otp:
        return gen_response(400, "OTP is required", {"success": False})

    if not frappe.db.exists("Validate Mobile OTP", mobile_no):
        return gen_response(400, "OTP not generated for this mobile number", {"success": False})

    doc = frappe.get_doc("Validate Mobile OTP", mobile_no)

    current_time = now_datetime()

    if current_time > doc.expiry_time:
        doc.delete(ignore_permissions=True)
        frappe.db.commit()
        return gen_response(400, "OTP has expired. Please request a new OTP.", {"success": False})
    
    if str(doc.otp) != str(otp):
        return gen_response(400, "Invalid OTP", {"success": False})
    
    user = frappe.db.get_value("User", {"email": email}, "name")
    if user:
        frappe.db.set_value("User", user, "is_onboarded", 1)  
        frappe.db.commit()

    return gen_response(200, "Mobile number verified successfully", {"success": True})


@frappe.whitelist(allow_guest=True)
def send_email_otp(email=None):
    try:
        if not email:
            return gen_response(500,"Email is required")

        # Validate email format
        if not frappe.utils.validate_email_address(email, throw=False):
            return gen_response(500,"Invalid Email Address")
            

        # Generate 6 digit OTP
        otp = str(random.randint(100000, 999999))
        expiry_time = add_to_date(now_datetime(), minutes=10)

        # Check if OTP already exists for this email
        existing_doc = frappe.db.get_value(
            "Validate Email OTP",
            {"email": email},
            "name"
        )

        if existing_doc:
            doc = frappe.get_doc("Validate Email OTP", existing_doc)
            doc.otp = otp
            doc.expiry_time = expiry_time
            doc.save(ignore_permissions=True)
        else:
            doc = frappe.get_doc({
                "doctype": "Validate Email OTP",
                "email": email,
                "otp": otp,
                "expiry_time": expiry_time
            })
            doc.insert(ignore_permissions=True)

        # Clean HTML body without indentation issues
        html_message = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <p>Hello,</p>

            <p>Your One-Time Password (OTP) for Stridenex login is:</p>

            <div style="
                font-size: 28px;
                font-weight: bold;
                letter-spacing: 4px;
                margin: 20px 0;
            ">
                {otp}
            </div>

            <p>This OTP will expire in 5 minutes.</p>

            <p>If you did not request this OTP, please ignore this email.</p>

            <hr>

            <p>
                Regards,<br>
                Stridenex Team
            </p>
        </body>
        </html>
        """

        frappe.sendmail(
            recipients=[email],
            subject="Stridenex Verification",
            message=html_message,
            now=True,
            header=["Stridenex Verification", "green"]
        )
        frappe.db.commit()


        return {
            "status": "success",
            "message": "OTP sent successfully"
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Send Email OTP Error")
        return {
            "status": "error",
            "message": str(e)
        }


@frappe.whitelist(allow_guest=True)
def validate_email_otp(email=None, otp=None):

    if not email:
        return gen_response(400, "Email is required" , {"success": False} )

    if not otp:
        return gen_response(400, "OTP is required", {"success": False})

    doc_name = frappe.db.get_value(
        "Validate Email OTP",
        {"email": email},
        "name"
    )

    if not doc_name:
        return gen_response(400, "OTP not generated for this email", {"success": False})

    doc = frappe.get_doc("Validate Email OTP", doc_name)


    if now_datetime() > doc.expiry_time:
        doc.delete(ignore_permissions=True)
        frappe.db.commit()
        return gen_response(400, "OTP has expired. Please request a new OTP.", {"success": False})

    
    if str(doc.otp) != str(otp):
        return gen_response(400, "Invalid OTP", {"success": False})
    
    # user = frappe.db.get_value("User", {"email": email}, "name")
    # if user:
    #     frappe.db.set_value("User", user, "is_onboarded", 1) 
    #     frappe.db.commit()

    return gen_response(200, "Email verified successfully", {"success": True})

