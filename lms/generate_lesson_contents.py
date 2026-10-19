import sys
import time
import requests
import frappe
import json
import re
from frappe.utils import md_to_html

API_KEY = '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'
GROQ_API_URL = 'https://api.groq.com/openai/v1/chat/completions'

def generate_lesson_content(course_title, chapter_title, lesson_title):
    headers = {
        'Authorization': f'Bearer {API_KEY}',
        'Content-Type': 'application/json'
    }
    
    prompt = (
        f"You are an expert instructor for the course '{course_title}'.\n"
        f"We are in the chapter '{chapter_title}'.\n"
        f"Write a very detailed, comprehensive lesson for the topic: '{lesson_title}'.\n"
        "Explain it in detail. Provide code examples if necessary.\n"
        "Format the content entirely in professional Markdown."
    )
    
    payload = {
        'model': 'openai/gpt-oss-20b',
        'messages': [
            {'role': 'system', 'content': 'You are a professional technical instructor.'},
            {'role': 'user', 'content': prompt}
        ],
        'temperature': 0.7,
        'max_tokens': 1000
    }
    
    retries = 10
    for attempt in range(retries):
        try:
            response = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=30)
            if response.status_code == 429:
                err_text = response.text
                print(f"Rate limited on attempt {attempt+1}.")
                match = re.search(r'try again in ([\d\.]+)s', err_text)
                wait_time = float(match.group(1)) + 1 if match else 10
                print(f"Waiting for {wait_time} seconds before retrying...")
                time.sleep(wait_time)
                continue
            
            response.raise_for_status()
            data = response.json()
            return data['choices'][0]['message']['content']
        except Exception as e:
            print(f"Error generating content for '{lesson_title}': {e}")
            try:
                print("Response:", response.text)
            except:
                pass
            time.sleep(5)
    return None

def run():
    lessons = frappe.get_all('Course Lesson', fields=['name', 'title', 'chapter', 'course', 'body'])
    
    for idx, lesson in enumerate(lessons):
        # Only fetch if it's really missing or very short
        if not lesson.body or len(lesson.body.strip()) < 100:
            print(f"[{idx+1}/{len(lessons)}] Generating content for: {lesson.title} ({lesson.name})")
            course_title = frappe.db.get_value('LMS Course', lesson.course, 'title') or lesson.course
            chapter_title = frappe.db.get_value('Course Chapter', lesson.chapter, 'title') or lesson.chapter
            
            content_md = generate_lesson_content(course_title, chapter_title, lesson.title)
            if content_md:
                # CONVERT TO HTML to fix UI issues
                html_content = md_to_html(content_md)
                
                doc = frappe.get_doc('Course Lesson', lesson.name)
                doc.body = html_content
                doc.content = html_content
                doc.save(ignore_permissions=True)
                frappe.db.commit()
                print(f" -> Successfully updated {lesson.title}")
            else:
                print(f" -> Failed to update {lesson.title}")
            
            time.sleep(2)
        else:
            # If it has content but it's raw markdown, convert it!
            if lesson.body and '## ' in lesson.body and '<h' not in lesson.body:
                print(f"[{idx+1}/{len(lessons)}] Converting Markdown to HTML for: {lesson.title}")
                html_content = md_to_html(lesson.body)
                doc = frappe.get_doc('Course Lesson', lesson.name)
                doc.body = html_content
                doc.content = html_content
                doc.save(ignore_permissions=True)
                frappe.db.commit()

    print("Done generating lesson contents.")
