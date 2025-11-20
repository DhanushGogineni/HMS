from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash
from database import init_db, get_db_connection, DATABASE
import sqlite3
import os
from functools import wraps
from datetime import datetime, timedelta

# --- App Setup ---
# Check and initialize database on app startup if it doesn't exist
if not os.path.exists(DATABASE):
    print("Database not found. Initializing database...")
    init_db()

app = Flask(__name__)
# Set a strong secret key for session security
app.secret_key = os.environ.get('SECRET_KEY', 'default_dev_secret_key_hms_123') 

# --- Database Connection and Cleanup ---

def get_db():
    """Helper to get DB connection on request and store it in the application context."""
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = get_db_connection()
    return db

@app.teardown_appcontext
def close_connection(exception):
    """Closes DB connection after request is complete."""
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# --- Authentication and Authorization Decorator ---

def login_required(role=None):
    """Decorator to enforce login and optional role-based access."""
    def wrapper(f):
        @wraps(f) # Important for Flask decorators
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('login'))
            
            if role and session.get('role') != role:
                flash('Access denied: Insufficient privileges.', 'danger')
                # Redirect user to their own dashboard
                if session['role'] == 'Admin':
                    return redirect(url_for('admin_dashboard'))
                if session['role'] == 'Doctor':
                    return redirect(url_for('doctor_dashboard'))
                if session['role'] == 'Patient':
                    return redirect(url_for('patient_dashboard'))
                return redirect(url_for('index'))

            return f(*args, **kwargs)
        return decorated_function
    return wrapper

# --- Common Routes ---

@app.route('/')
def index():
    """Root route: redirects logged-in users to their dashboard."""
    if 'user_id' in session:
        role = session['role']
        if role == 'Admin':
            return redirect(url_for('admin_dashboard'))
        elif role == 'Doctor':
            return redirect(url_for('doctor_dashboard'))
        elif role == 'Patient':
            return redirect(url_for('patient_dashboard'))
    
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handles user login."""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        # Check for active user with the given username
        user = db.execute('SELECT * FROM user WHERE username = ? AND is_active = 1', (username,)).fetchone()

        if user and check_password_hash(user['password_hash'], password):
            session.clear() # Clear any old session data
            session['user_id'] = user['user_id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['name'] = user['name']
            flash(f"Welcome back, {user['name']}!", 'success')

            if user['role'] == 'Admin':
                return redirect(url_for('admin_dashboard'))
            elif user['role'] == 'Doctor':
                return redirect(url_for('doctor_dashboard'))
            elif user['role'] == 'Patient':
                return redirect(url_for('patient_dashboard'))
        else:
            flash('Invalid username or password, or your account is inactive.', 'danger')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Handles patient registration only."""
    if request.method == 'POST':
        name = request.form['name']
        username = request.form['username']
        password = request.form['password']
        password_hash = generate_password_hash(password)
        db = get_db()
        cursor = db.cursor()

        try:
            # 1. Insert into User table (role is hardcoded as Patient)
            cursor.execute('''
                INSERT INTO user (username, password_hash, role, name)
                VALUES (?, ?, ?, ?)
            ''', (username, password_hash, 'Patient', name))
            user_id = cursor.lastrowid
            
            # 2. Insert into Patient table
            cursor.execute('''
                INSERT INTO patient (patient_id)
                VALUES (?)
            ''', (user_id,))
            
            db.commit()
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))

        except sqlite3.IntegrityError:
            flash('Username already exists. Please choose a different one.', 'danger')
        except Exception as e:
            db.rollback()
            flash(f'An unexpected error occurred during registration: {e}', 'danger')

    return render_template('register.html')

@app.route('/logout')
def logout():
    """Clears the session and logs the user out."""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

# =========================================================================
# --- ADMIN ROUTES ---
# =========================================================================

@app.route('/admin/dashboard', methods=['GET'])
@login_required(role='Admin')
def admin_dashboard():
    db = get_db()
    
    # 1. Core Statistics
    stats = db.execute('''
        SELECT 
            (SELECT COUNT(*) FROM user WHERE role='Doctor' AND is_active = 1) AS active_doctors,
            (SELECT COUNT(*) FROM user WHERE role='Patient' AND is_active = 1) AS active_patients,
            (SELECT COUNT(*) FROM appointment WHERE status = 'Booked') AS upcoming_appointments,
            (SELECT COUNT(*) FROM appointment) AS total_appointments
    ''').fetchone()
    
    # 2. Registered Doctors
    doctors = db.execute('''
        SELECT u.user_id, u.name, d.specialization_name, u.is_active
        FROM user u
        LEFT JOIN doctor d ON u.user_id = d.doctor_id
        WHERE u.role = 'Doctor'
        ORDER BY u.name
    ''').fetchall()

    # 3. Registered Patients
    patients = db.execute('''
        SELECT user_id, name, contact_info, is_active
        FROM user 
        WHERE role = 'Patient'
        ORDER BY name
    ''').fetchall()

    # 4. Upcoming Appointments (Limited view)
    upcoming_appointments = db.execute('''
        SELECT 
            a.app_id, 
            p_user.name AS patient_name, 
            d_user.name AS doctor_name,
            dept.name AS department_name
        FROM appointment a
        JOIN user p_user ON a.patient_id = p_user.user_id
        JOIN user d_user ON a.doctor_id = d_user.user_id
        JOIN doctor d ON a.doctor_id = d.doctor_id
        JOIN department dept ON d.dept_id = dept.dept_id
        WHERE a.status = 'Booked'
        ORDER BY a.date, a.time
        LIMIT 10 
    ''').fetchall()

    # 5. All departments for the Add Doctor Form
    departments = db.execute('SELECT dept_id, name FROM department ORDER BY name').fetchall()
    
    return render_template('admin/dashboard.html', 
                           stats=stats, 
                           doctors=doctors,
                           patients=patients,
                           appointments=upcoming_appointments,
                           departments=departments)

@app.route('/admin/add_doctor', methods=['POST'])
@login_required(role='Admin')
def add_doctor():
    """Handles adding a new Doctor profile."""
    name = request.form['name']
    username = request.form['username']
    password = request.form['password']
    dept_id = request.form['dept_id']
    contact_info = request.form['contact_info']
    
    db = get_db()
    cursor = db.cursor()
    password_hash = generate_password_hash(password)

    try:
        # Find the specialization name for the doctor table
        dept = db.execute('SELECT name FROM department WHERE dept_id = ?', (dept_id,)).fetchone()
        if not dept:
            flash('Invalid Department ID selected.', 'danger')
            return redirect(url_for('admin_dashboard'))

        specialization_name = dept['name']

        # 1. Insert into User table
        cursor.execute('''
            INSERT INTO user (username, password_hash, role, name, contact_info)
            VALUES (?, ?, ?, ?, ?)
        ''', (username, password_hash, 'Doctor', name, contact_info))
        doctor_id = cursor.lastrowid
        
        # 2. Insert into Doctor table
        cursor.execute('''
            INSERT INTO doctor (doctor_id, dept_id, specialization_name)
            VALUES (?, ?, ?)
        ''', (doctor_id, dept_id, specialization_name))
        
        db.commit()
        flash(f'Doctor {name} added successfully!', 'success')

    except sqlite3.IntegrityError:
        flash('Username already exists. Please choose a different one.', 'danger')
    except Exception as e:
        db.rollback()
        flash(f'An unexpected error occurred: {e}', 'danger')
        
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/toggle_user_status/<int:user_id>/<string:action>', methods=['POST'])
@login_required(role='Admin')
def toggle_user_status(user_id, action):
    """Handles blacklisting/deleting (setting is_active=0) or activating (is_active=1) users."""
    db = get_db()
    
    if action == 'blacklist' or action == 'delete':
        new_status = 0
        status_word = 'Blacklisted'
        flash_category = 'warning'
    elif action == 'activate':
        new_status = 1
        status_word = 'Activated'
        flash_category = 'success'
    else:
        flash('Invalid action requested.', 'danger')
        return redirect(url_for('admin_dashboard'))

    try:
        # Prevent Admin from blacklisting themselves
        if user_id == session['user_id']:
            flash('You cannot change your own status.', 'danger')
            return redirect(url_for('admin_dashboard'))
            
        cursor = db.cursor()
        cursor.execute('''
            UPDATE user SET is_active = ? WHERE user_id = ?
        ''', (new_status, user_id))
        
        db.commit()
        
        # Get user name for confirmation message
        user = db.execute('SELECT name, role FROM user WHERE user_id = ?', (user_id,)).fetchone()
        if user:
            flash(f"{user['role']} '{user['name']}' has been {status_word}!", flash_category)
        else:
            flash(f"User ID {user_id} status updated to {status_word}.", flash_category)

    except Exception as e:
        db.rollback()
        flash(f'Database error during status update: {e}', 'danger')

    return redirect(url_for('admin_dashboard'))


# =========================================================================
# --- DOCTOR ROUTES (PLACEHOLDERS) ---
# =========================================================================

@app.route('/doctor/dashboard')
@login_required(role='Doctor')
def doctor_dashboard():
    # Placeholder implementation
    doctor_id = session['user_id']
    db = get_db()
    
    today = datetime.now().strftime('%Y-%m-%d')
    seven_days_later = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')

    appointments = db.execute('''
        SELECT a.app_id, a.date, a.time, u.name AS patient_name, u.contact_info
        FROM appointment a
        JOIN user u ON a.patient_id = u.user_id
        WHERE a.doctor_id = ? 
          AND a.status = 'Booked'
          AND a.date BETWEEN ? AND ?
        ORDER BY a.date, a.time
    ''', (doctor_id, today, seven_days_later)).fetchall()
    
    return render_template('doctor/dashboard.html', appointments=appointments)

# Placeholder: Route for setting doctor availability
@app.route('/doctor/set_availability', methods=['GET', 'POST'])
@login_required(role='Doctor')
def set_doctor_availability():
    flash("Functionality to set doctor availability needs to be implemented!", "info")
    return redirect(url_for('doctor_dashboard'))


# =========================================================================
# --- PATIENT ROUTES (PLACEHOLDERS) ---
# =========================================================================

@app.route('/patient/dashboard')
@login_required(role='Patient')
def patient_dashboard():
    # Placeholder implementation
    patient_id = session['user_id']
    db = get_db()
    
    # Fetch all departments for searching
    departments = db.execute('SELECT * FROM department ORDER BY name').fetchall()
    
    # Fetch upcoming appointments
    upcoming_appointments = db.execute('''
        SELECT a.app_id, a.date, a.time, u.name AS doctor_name, d.specialization_name, a.status
        FROM appointment a
        JOIN user u ON a.doctor_id = u.user_id
        JOIN doctor d ON a.doctor_id = d.doctor_id
        WHERE a.patient_id = ? AND a.status = 'Booked'
        ORDER BY a.date, a.time
    ''', (patient_id,)).fetchall()
    
    # Fetch past appointments for history
    past_appointments = db.execute('''
        SELECT a.app_id, a.date, u.name AS doctor_name, d.specialization_name, t.diagnosis, t.prescription
        FROM appointment a
        JOIN user u ON a.doctor_id = u.user_id
        JOIN doctor d ON a.doctor_id = d.doctor_id
        LEFT JOIN treatment t ON a.app_id = t.app_id
        WHERE a.patient_id = ? AND a.status = 'Completed'
        ORDER BY a.date DESC
    ''', (patient_id,)).fetchall()

    return render_template('patient/dashboard.html', 
                           departments=departments, 
                           upcoming_appointments=upcoming_appointments,
                           past_appointments=past_appointments)

# Placeholder: Route for searching doctors and booking
@app.route('/patient/book_appointment', methods=['GET', 'POST'])
@login_required(role='Patient')
def book_appointment():
    flash("Appointment search and booking logic needs to be implemented!", "info")
    return redirect(url_for('patient_dashboard'))


# --- Run the App ---
if __name__ == '__main__':
    print(f"Starting Hospital Management System. Database is at: {DATABASE}")
    app.run(debug=True)