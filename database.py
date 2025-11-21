# database.py
import sqlite3
from werkzeug.security import generate_password_hash
import os

DATABASE = 'hms.db'

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE)
    # Allows accessing columns by name instead of index
    conn.row_factory = sqlite3.Row 
    return conn

def init_db():
    """Creates all necessary tables and seeds the initial Admin user and Departments."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # --- TABLE CREATION (Ensure all tables are created first) ---
    
    # 1. User Table (Authentication & Common Details)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('Admin', 'Doctor', 'Patient')),
            name TEXT NOT NULL,
            contact_info TEXT,
            is_active BOOLEAN DEFAULT 1 
        );
    ''')

    # 2. Department Table (Specializations)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS department (
            dept_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT
        );
    ''')
    
    # 3. Doctor Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS doctor (
            doctor_id INTEGER PRIMARY KEY,
            dept_id INTEGER NOT NULL,
            specialization_name TEXT NOT NULL,
            FOREIGN KEY (doctor_id) REFERENCES user (user_id),
            FOREIGN KEY (dept_id) REFERENCES department (dept_id)
        );
    ''')
    
    # 4. Patient Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS patient (
            patient_id INTEGER PRIMARY KEY,
            dob TEXT,
            FOREIGN KEY (patient_id) REFERENCES user (user_id)
        );
    ''')
    
    # 5. DoctorAvailability Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS doctor_availability (
            avail_id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            UNIQUE(doctor_id, date, start_time), 
            FOREIGN KEY (doctor_id) REFERENCES doctor (doctor_id)
        );
    ''')
    
    # 6. Appointment Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS appointment (
            app_id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            doctor_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('Booked', 'Completed', 'Cancelled')),
            UNIQUE(doctor_id, date, time), 
            FOREIGN KEY (patient_id) REFERENCES patient (patient_id),
            FOREIGN KEY (doctor_id) REFERENCES doctor (doctor_id)
        );
    ''')
    
    # 7. Treatment Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS treatment (
            treatment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_id INTEGER UNIQUE NOT NULL, 
            diagnosis TEXT NOT NULL,
            prescription TEXT NOT NULL,
            notes TEXT,
            FOREIGN KEY (app_id) REFERENCES appointment (app_id)
        );
    ''')

    # --- DEPARTMENT SEEDING (NEW CODE) ---
    departments_to_add = [
        ('Cardiology', 'Heart and blood vessels.'),
        ('Neurology', 'Nervous system disorders.'),
        ('Pediatrics', 'Children and adolescents health.'),
        ('Orthopedics', 'Musculoskeletal system.'),
        ('General Practice', 'Primary health care.'),
    ]
    
    # Check if departments exist before inserting to prevent duplicate keys
    for name, description in departments_to_add:
        cursor.execute("SELECT dept_id FROM department WHERE name = ?", (name,))
        if cursor.fetchone() is None:
            cursor.execute('''
                INSERT INTO department (name, description)
                VALUES (?, ?);
            ''', (name, description))
            print(f"Seeded department: {name}")

    # --- ADMIN SEEDING (Existing Code) ---
    admin_username = 'admin'
    admin_password = 'adminpassword' 
    
    cursor.execute("SELECT user_id FROM user WHERE username = ?", (admin_username,))
    if cursor.fetchone() is None:
        admin_password_hash = generate_password_hash(admin_password)
        cursor.execute('''
            INSERT INTO user (username, password_hash, role, name)
            VALUES (?, ?, ?, ?);
        ''', (admin_username, admin_password_hash, 'Admin', 'Super Admin Staff'))
        print(f"Admin user created: {admin_username} / {admin_password}")

    conn.commit()
    conn.close()

if __name__ == '__main__':
    # Running init_db() will ensure tables and data are created/present
    init_db()