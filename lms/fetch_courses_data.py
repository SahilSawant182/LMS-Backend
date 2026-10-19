import frappe

def run():
    for course_name in ['python-programming-fundamentals', 'advanced-python-development']:
        print(f"\nCourse: {course_name}")
        try:
            course = frappe.get_doc('LMS Course', course_name)
        except Exception as e:
            print(f"Error fetching course {course_name}: {e}")
            continue
        print("Chapters:")
        
        if hasattr(course, 'chapters'):
            for ch in course.chapters:
                print(f"  - {ch.chapter} / {getattr(ch, 'title', '')}")
                try:
                    ch_doc = frappe.get_doc('Course Chapter', ch.chapter)
                    if hasattr(ch_doc, 'lessons'):
                        for less in ch_doc.lessons:
                             print(f"    - {less.lesson}")
                except Exception as e:
                    pass
        else:
            chapters = frappe.get_all('Course Chapter', filters={'course': course_name}, fields=['name', 'title', 'idx'], order_by='idx asc')
            for ch in chapters:
                print(f"  - {ch.name} / {ch.title}")
                lessons = frappe.get_all('Course Lesson', filters={'chapter': ch.name}, fields=['name', 'title', 'idx'], order_by='idx asc')
                for less in lessons:
                     print(f"    - {less.name} / {less.title}")
