import sys
sys.path.insert(0, '/home/dev/lms-bench/apps/frappe')
import frappe

frappe.init(site='devlms.stridenex.ai', sites_path='/home/dev/lms-bench/sites')
frappe.connect()

courses_data = {
    "devops-and-ci-cd": [
        {"title": "Version Control with Git", "lessons": ["Git Basics", "GitHub Workflows"]},
        {"title": "Containerization", "lessons": ["Docker Fundamentals", "Docker Compose"]},
        {"title": "CI/CD Pipelines", "lessons": ["Introduction to Jenkins", "Building Automated Pipelines"]},
        {"title": "Infrastructure as Code", "lessons": ["Basics of Terraform", "Automating Deployments"]},
        {"title": "Monitoring and Logging", "lessons": ["Monitoring Strategies", "Modern DevOps Workflows"]}
    ]
}

def create_course_content():
    for course, chapters in courses_data.items():
        print(f"Processing course: {course}")
        if not frappe.db.exists("LMS Course", course):
            print(f"Course {course} not found, skipping...")
            continue
        
        for ch_idx, chapter in enumerate(chapters, start=1):
            ch_title = chapter["title"]
            ch_name = frappe.db.exists("Course Chapter", {"course": course, "title": ch_title})
            if not ch_name:
                ch_doc = frappe.get_doc({
                    "doctype": "Course Chapter",
                    "course": course,
                    "title": ch_title,
                    "idx": ch_idx
                })
                ch_doc.insert(ignore_permissions=True)
                ch_name = ch_doc.name
                print(f"  Created Chapter: {ch_title}")
            else:
                print(f"  Chapter exists: {ch_title}")
            
            for les_idx, lesson in enumerate(chapter["lessons"], start=1):
                les_title = lesson
                les_name = frappe.db.exists("Course Lesson", {"chapter": ch_name, "title": les_title})
                if not les_name:
                    les_doc = frappe.get_doc({
                        "doctype": "Course Lesson",
                        "course": course,
                        "chapter": ch_name,
                        "title": les_title,
                        "idx": les_idx,
                        "body": f"This is the content for {les_title}."
                    })
                    les_doc.insert(ignore_permissions=True)
                    print(f"    Created Lesson: {les_title}")
                else:
                    print(f"    Lesson exists: {les_title}")
    
    frappe.db.commit()
    print("Done!")

create_course_content()
