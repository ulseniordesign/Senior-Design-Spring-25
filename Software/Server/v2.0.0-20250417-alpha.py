#!/usr/bin/env python3

# -----------------------------------------------------------------------------
# Project: Automated School Bus 
# Author(s): Madison Lee, Kenrick Williams, Roland Simmons 
# Institution: UNIVERSITY OF LOUISIANA AT LAFAYETTE 
# Course: Senior Design (EECE 460)
# Instructor: Dr. Paul Darby 
# Date: February 1, 2025

#
# Description:
# # This software functions as the main server for the Schoolbus Automation system. It listens
# for connections from bus-mounted clients over TCP, processes incoming RFID and
# GPS data, logs student attendance, and stores records in a MySQL database. It
# also provides a text-based admin interface for managing students, querying logs,
# and interacting with connected buses.

# Dependencies:
# - Python 3.x
# - pyserial library (`pip install pyserial`)
# - binascii library 
# - time library
# - curses library
# - threading library
# - queue library
# - socket library
# - pymysql library
# - os library
# 
# License:
# MIT License (see below)
#
# Copyright (c) 2025 Madison Lee, Kenrick Williams, Roland Simmons 
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR 
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, 
# FITNESS FOR A PARTICULAR PURPOSE, AND NONINFRINGEMENT.
# -----------------------------------------------------------------------------


import curses
import threading
import queue
import socket
import pymysql
import time
import os
from datetime import datetime
from wcwidth import wcswidth  # For accurate emoji and wide character rendering

# ------------------ GLOBAL VARIABLES ------------------ #
server_logs = queue.Queue()
LOG_HISTORY = []
MAX_LOG_LINES = 25
DEBOUNCE_SECONDS = 5
rfid_timestamps = {}
client_bus_map = {}  # IP to Bus ID 

# --------------- MYSQL CONNECTION --------------- #
# Establishes and returns a connection to the local MySQL database.
# Update the credentials and database name as needed.

def connect():
    return pymysql.connect(
        host="localhost",
        user="root",
        password="YOUR PASSWORD",
        database="YOUR DATABASE"
    )


# --------------- HANDLE CLIENT CONNECTION --------------- #
# Handles communication with a connected bus client.
# Processes handshake messages, pings, and RFID+GPS data,
# logs valid attendance entries, and manages client disconnection.

def handle_client(client_socket, addr):
    server_logs.put(f"🔌 Connected to {addr}")
    try:
        while True:
            data = client_socket.recv(1024).decode('utf-8', errors='ignore').strip()
            if not data:
                server_logs.put(f"❗ Client {addr} disconnected.")
                break

            if data.startswith("HELLO BUS:"):
                bus_id = data.split("HELLO BUS:")[1].strip()
                client_bus_map[bus_id] = client_socket
                server_logs.put(f"🚌 Registered {bus_id} from {addr}")
                continue

            if data.startswith("PONG"):
                # Find the bus ID for this socket
                bus_id = next((bid for bid, sock in client_bus_map.items() if sock == client_socket), "Unknown")
                formatted = f"📡 Ping response from {bus_id}: {data}"
                server_logs.put(formatted)
                LOG_HISTORY.append(formatted)
                if len(LOG_HISTORY) > MAX_LOG_LINES:
                    LOG_HISTORY.pop(0)
                continue

            server_logs.put(f"📥 Received: {data}")

            parts = data.split(" | ")
            if len(parts) == 4:
                try:
                    rfid = parts[0].replace("RFID:", "").strip()
                    status = parts[1].replace("STATUS:", "").strip()
                    gps_time = parts[2].replace("GPS:", "").strip()
                    coords = parts[3].strip()

                    now = time.time()
                    if (now - rfid_timestamps.get(rfid, 0)) < DEBOUNCE_SECONDS:
                        continue
                    rfid_timestamps[rfid] = now

                    name = get_student_name(rfid)
                    if name:
                        log_attendance(name, status, f"{gps_time} | {coords}")
                        server_logs.put(f"📝 Logged: {name} - {status}")
                except Exception as e:
                    server_logs.put(f"⚠️ Error processing: {e}")

    except Exception as e:
        server_logs.put(f"⚠️ Client error: {e}")
    finally:
        for bus_id, sock in list(client_bus_map.items()):
            if sock == client_socket:
                del client_bus_map[bus_id]
                server_logs.put(f"❎ Removed {bus_id} from active list")
        client_socket.close()
        server_logs.put(f"🔴 Disconnected: {addr}")


# --------------- SERVER THREAD STARTUP --------------- #
# Starts the TCP server to accept incoming client (bus) connections.
# Spawns a new thread to handle each connected client.

def start_server_thread():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("YOUR IP", 9999))
    server_socket.listen(5)
    server_logs.put("🟢 Server listening on YOUR IP:9999")

    while True:
        client_socket, addr = server_socket.accept()
        threading.Thread(target=handle_client, args=(client_socket, addr), daemon=True).start()


# --------------- Database Functions --------------- #
# Retrieves the student name associated with a given RFID tag
# from the MySQL database. Returns None if not found.

def get_student_name(rfid):
    conn = connect()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT name FROM students WHERE rfid_tag = %s", (rfid,))
        result = cursor.fetchone()
        return result[0] if result else None
    finally:
        cursor.close()
        conn.close()

# ---------------- Log Attendance Section ----------- # 
# Logs a student's attendance entry with timestamp, name, status, and GPS data
# into a daily text file inside the "logs" directory.

def log_attendance(name, status, gps):
    today = datetime.now().strftime("%Y-%m-%d")
    if not os.path.exists("logs"):
        os.makedirs("logs")
    with open(f"logs/{today}_attendance.txt", "a") as f:
        f.write(f"{datetime.now().strftime('%H:%M:%S')} | {name} | {status} | {gps}\n")

# --------------- Add a Student Section ------------ # 
# Adds a new student to the MySQL database via a text-based UI.
# Prompts for name, RFID, bus ID, and school, then stores the data with error handling.

def add_student(stdscr):
    """Add a student with robust feedback"""
    while True:
        try:
            stdscr.clear()
            curses.echo()

            stdscr.addstr(1, 2, "ADD NEW STUDENT", curses.A_BOLD)
            stdscr.addstr(3, 2, "Name: ")
            name = stdscr.getstr().decode('utf-8')
            if not name:
                raise ValueError("Name cannot be empty")

            stdscr.addstr(4, 2, "RFID: ")
            rfid = stdscr.getstr().decode('utf-8')
            if not rfid:
                raise ValueError("RFID cannot be empty")

            stdscr.addstr(5, 2, "Bus ID: ")
            bus = stdscr.getstr().decode('utf-8')

            stdscr.addstr(6, 2, "School: ")
            school = stdscr.getstr().decode('utf-8')

            curses.noecho()

            conn = None
            try:
                conn = connect()
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO students (name, rfid_tag, Bus_ID, school) VALUES (%s, %s, %s, %s)",
                    (name, rfid, bus, school)
                )
                conn.commit()

                stdscr.clear()
                stdscr.addstr(1, 2, "✅ STUDENT ADDED", curses.A_BOLD)
                stdscr.addstr(3, 2, f"Name: {name}")
                stdscr.addstr(4, 2, f"RFID: {rfid}")
                stdscr.addstr(5, 2, f"Bus: {bus}")
                stdscr.addstr(6, 2, f"School: {school}")
                stdscr.addstr(8, 2, "Press any key to continue...")
                stdscr.refresh()
                server_logs.put(f"✅ Added student: {name} (RFID: {rfid}, Bus: {bus}, School: {school})")
                stdscr.getch()
                return

            except pymysql.err.IntegrityError as e:
                stdscr.clear()
                msg = f"RFID {rfid} already exists!" if "rfid_tag" in str(e) else "Database error: " + str(e)
                stdscr.addstr(1, 2, "❌ ERROR", curses.A_BOLD)
                stdscr.addstr(3, 2, msg)
                stdscr.addstr(5, 2, "Press any key to try again...")
                server_logs.put(f"❌ Failed to add student: {msg}")
                stdscr.refresh()
                stdscr.getch()
                continue

            except Exception as e:
                stdscr.clear()
                stdscr.addstr(1, 2, "❌ DATABASE ERROR", curses.A_BOLD)
                stdscr.addstr(3, 2, f"Error: {str(e)}")
                stdscr.addstr(5, 2, "Press any key to continue...")
                server_logs.put(f"❌ Error adding student: {e}")
                stdscr.refresh()
                stdscr.getch()
                return

            finally:
                if conn:
                    conn.close()

        except ValueError as e:
            stdscr.clear()
            stdscr.addstr(1, 2, "❌ INPUT ERROR", curses.A_BOLD)
            stdscr.addstr(3, 2, str(e))
            stdscr.addstr(5, 2, "Press any key to try again...")
            stdscr.refresh()
            stdscr.getch()
            continue

        except curses.error:
            stdscr.clear()
            stdscr.addstr(0, 0, "⚠️ Terminal too small! Resize and try again.")
            stdscr.refresh()
            stdscr.getch()
            return

# ----------- Delete a student from Database Section --------------- # 
# Deletes a student from the database by name using a text-based interface.
# Displays matching records for confirmation before removal.

def delete_student(stdscr):
    """Delete a student by name with validation"""
    while True:
        stdscr.clear()
        curses.echo()
        try:
            stdscr.addstr("\nEnter the name of the student to delete: ")
            name = stdscr.getstr().decode('utf-8')
            if not name:
                raise ValueError("Name cannot be empty")
            
            curses.noecho()
            
            conn = connect()
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT * FROM students WHERE name = %s", (name,))
                results = cursor.fetchall()
                
                if not results:
                    server_logs.put(f"❌ No student found: {name}")
                    stdscr.addstr("\nNo student found with that name.\nPress any key...")
                    stdscr.getch()
                    return
                    
                stdscr.clear()
                stdscr.addstr("\nFound the following student(s):\n")
                for student in results:
                    stdscr.addstr(f"- Name: {student[1]}, RFID: {student[2]}, Bus: {student[3]}\n")
                
                stdscr.addstr("\nDelete these students? (y/n): ")
                stdscr.refresh()
                confirm = stdscr.getch()
                
                if confirm == ord('y'):
                    cursor.execute("DELETE FROM students WHERE name = %s", (name,))
                    conn.commit()
                    server_logs.put(f"🗑️ Deleted student: {name}")
                    stdscr.addstr("\n\nStudent(s) deleted! Press any key...")
                    stdscr.getch()
                else:
                    stdscr.addstr("\n\nDeletion cancelled. Press any key...")
                    stdscr.getch()
                return
            except Exception as e:
                server_logs.put(f"❌ Error deleting student: {e}")
                stdscr.addstr(f"\n\nError: {e}\nPress any key...")
                stdscr.getch()
                return
            finally:
                cursor.close()
                conn.close()
                
        except ValueError as e:
            curses.noecho()
            stdscr.addstr(f"\n\nError: {e}\nPress any key...")
            stdscr.getch()
            continue
        except curses.error:
            stdscr.clear()
            stdscr.addstr(0, 0, "Screen too small! Resize terminal.")
            stdscr.refresh()
            stdscr.getch()
            return


# --------------------- Search Student Section --------------- # 
# Searches for a student by name and displays their most recent bus activity
# using today's attendance log and database lookup.

def search_student(stdscr):
    curses.echo()
    stdscr.clear()
    stdscr.addstr(1, 2, "SEARCH STUDENT", curses.A_BOLD)
    stdscr.addstr(3, 2, "Enter Student Name: ")
    name = stdscr.getstr().decode('utf-8').strip()
    curses.noecho()

    conn = connect()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT rfid_tag FROM students WHERE name = %s", (name,))
        row = cursor.fetchone()
        if not row:
            stdscr.addstr(5, 2, f"❌ No student found with name '{name}'")
            server_logs.put(f"❌ Search: No student found with name '{name}'")
        else:
            rfid = row[0]
            today = datetime.now().strftime("%Y-%m-%d")
            log_path = f"logs/{today}_attendance.txt"
            last_line = None
            if os.path.exists(log_path):
                with open(log_path, 'r') as f:
                    lines = f.readlines()
                    for line in reversed(lines):
                        if name in line:
                            last_line = line.strip()
                            break
            if last_line:
                parts = last_line.split(" | ")
                time_str = parts[0]
                status = parts[2]
                gps_time = parts[3] if len(parts) > 3 else "N/A"
                coords = parts[4] if len(parts) > 4 else "N/A"
                location = f"{gps_time} @ {coords}"
                if status.lower() == "onboard":
                    msg = f"🚌 {name} is currently ONBOARD bus at {location} (last seen {time_str})"
                else:
                    msg = f"📤 {name} OFFBOARDED bus at {location} (last seen {time_str})"
                stdscr.addstr(5, 2, msg)
                server_logs.put(f"🔍 Search result: {msg}")
            else:
                stdscr.addstr(5, 2, f"⚠️ No recent log entry for {name} today.")
                server_logs.put(f"⚠️ No log entry for {name} today.")
    except Exception as e:
        stdscr.addstr(5, 2, f"❌ Error: {e}")
        server_logs.put(f"❌ Search error: {e}")
    finally:
        cursor.close()
        conn.close()

    stdscr.addstr(7, 2, "Press any key to return...")
    stdscr.refresh()
    stdscr.getch()



# Safely truncates a string to fit within a specified display width,
# accounting for wide or multi-width characters (e.g. emojis, CJK).

def safe_truncate(s, max_width):
    truncated = ""
    total = 0
    for ch in s:
        ch_width = wcswidth(ch)
        if ch_width < 0:
            continue  # skip unprintable chars
        if total + ch_width > max_width:
            break
        truncated += ch
        total += ch_width
    return truncated



# --------------- PING BUS FEATURE --------------- #
# Sends a PING request to a connected bus client by Bus ID.
# Waits briefly for a response and displays the result in the UI.

def ping_bus(stdscr):
    curses.echo()
    stdscr.clear()
    stdscr.addstr(1, 2, "PING A BUS", curses.A_BOLD)
    stdscr.addstr(3, 2, "Enter Bus ID: ")
    bus_id = stdscr.getstr().decode('utf-8').strip()
    curses.noecho()
    stdscr.clear()

    if bus_id in client_bus_map:
        client_socket = client_bus_map[bus_id]
        try:
            client_socket.sendall(b"PING\n")
            server_logs.put(f"📡 Sent PING to {bus_id}, waiting for response...")
            
            # Wait for a moment to let handle_client log the response
            start_time = time.time()
            response_found = None

            while time.time() - start_time < 5.0:
                time.sleep(0.1)
                for line in reversed(LOG_HISTORY):
                    if f"Ping response from {bus_id}:" in line:
                        response_found = line
                        break
                if response_found:
                    break

            if response_found:
                stdscr.addstr(1, 2, f"📡 {response_found.strip()}")
            else:
                stdscr.addstr(1, 2, f"⏱️ No response from {bus_id}")

        except Exception as e:
            server_logs.put(f"❌ Error pinging {bus_id}: {e}")
            stdscr.addstr(1, 2, f"❌ Error: {e}")
    else:
        stdscr.addstr(1, 2, f"❌ Bus '{bus_id}' not connected.")

    stdscr.addstr(3, 2, "Press any key to return...")
    stdscr.refresh()
    stdscr.getch()

# --------------- Bus Roll Section ----------- # 
# Queries the database for all students assigned to a specific Bus ID
# and displays the list in the terminal UI.

def bus_roll_query(stdscr):
    curses.echo()
    stdscr.clear()
    stdscr.addstr(1, 2, "BUS ROLL QUERY", curses.A_BOLD)
    stdscr.addstr(3, 2, "Enter Bus ID: ")
    bus_id = stdscr.getstr().decode('utf-8').strip()
    curses.noecho()
    
    conn = connect()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT name FROM students WHERE Bus_ID = %s", (bus_id,))
        students = cursor.fetchall()

        if not students:
            msg = f"❌ No students found for Bus ID '{bus_id}'"
            stdscr.addstr(5, 2, msg)
            server_logs.put(f"🔍 Roll query: {msg}")
        else:
            stdscr.addstr(5, 2, f"🚌 Students assigned to Bus '{bus_id}':")
            server_logs.put(f"🔍 Roll query for Bus {bus_id} returned {len(students)} student(s).")
            for i, (name,) in enumerate(students, start=6):
                stdscr.addstr(i, 4, f"- {name}")
    except Exception as e:
        stdscr.addstr(5, 2, f"❌ Error: {e}")
        server_logs.put(f"❌ Roll query error: {e}")
    finally:
        cursor.close()
        conn.close()

    stdscr.addstr(len(students) + 7 if students else 7, 2, "Press any key to return...")
    stdscr.refresh()
    stdscr.getch()

# --------------- Query Entire Database -------------# 
# Displays all registered students from the database,
# including their names and associated schools, in alphabetical order.

def view_all_students(stdscr):
    stdscr.clear()
    stdscr.addstr(1, 2, "ALL REGISTERED STUDENTS", curses.A_BOLD)
    conn = connect()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT name, school FROM students ORDER BY name")
        students = cursor.fetchall()
        if not students:
            stdscr.addstr(3, 2, "❌ No students found in the database.")
            server_logs.put("🔍 Full DB query: No students found.")
        else:
            stdscr.addstr(3, 2, f"📋 Total Students: {len(students)}")
            for i, (name, school) in enumerate(students, start=5):
                stdscr.addstr(i, 4, f"- {name} ({school})")
            server_logs.put(f"📋 Full DB query returned {len(students)} student(s).")
    except Exception as e:
        stdscr.addstr(3, 2, f"❌ Error: {e}")
        server_logs.put(f"❌ DB query error: {e}")
    finally:
        cursor.close()
        conn.close()
    stdscr.addstr(len(students) + 6 if students else 6, 2, "Press any key to return...")
    stdscr.refresh()
    stdscr.getch()



# --------------- Clear Database ------------# 
# Deletes all student records from the database after confirmation.
# Prompts the user and logs the operation result.

def clear_all_students(stdscr):
    curses.echo()
    stdscr.clear()
    stdscr.addstr(1, 2, "CLEAR ENTIRE DATABASE", curses.A_BOLD)
    stdscr.addstr(3, 2, "Are you sure you want to delete ALL students? (yes/no): ")
    confirm = stdscr.getstr().decode('utf-8').strip().lower()
    curses.noecho()

    if confirm != "yes":
        stdscr.addstr(5, 2, "❎ Operation cancelled.")
        stdscr.refresh()
        stdscr.getch()
        return

    conn = connect()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM students")
        conn.commit()
        msg = "🧹 All student records cleared from database."
        stdscr.addstr(5, 2, msg)
        server_logs.put(msg)
    except Exception as e:
        stdscr.addstr(5, 2, f"❌ Error: {e}")
        server_logs.put(f"❌ Clear DB error: {e}")
    finally:
        cursor.close()
        conn.close()
    stdscr.addstr(7, 2, "Press any key to return...")
    stdscr.refresh()
    stdscr.getch()

# --------------- CURSES UI --------------- #
# Main curses-based UI loop for the server interface.
# Displays menu options, handles user input, and shows real-time logs and status updates.

def curses_main(stdscr):
    MIN_HEIGHT = 24
    MIN_WIDTH = 100
    curses.start_color()
    curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_RED, curses.COLOR_BLACK)

    while True:
        height, width = stdscr.getmaxyx()
        if height < MIN_HEIGHT or width < MIN_WIDTH:
            stdscr.clear()
            stdscr.addstr(0, 0, "⚠️ Screen Too Small ⚠️", curses.A_BOLD | curses.A_BLINK)
            stdscr.addstr(2, 0, f"Current: {width}x{height}", curses.A_BOLD)
            stdscr.addstr(3, 0, f"Required: At least {MIN_WIDTH}x{MIN_HEIGHT}")
            stdscr.addstr(5, 0, "Please resize your terminal window")
            stdscr.addstr(7, 0, "Press R to refresh or Q to quit")
            stdscr.refresh()
            while True:
                c = stdscr.getch()
                if c in (ord('r'), ord('R')):
                    break
                elif c in (ord('q'), ord('Q')):
                    return
            continue

        curses.curs_set(0)
        curses.noecho()
        curses.cbreak()

        menu_width = 40
        log_width = width - menu_width - 1
        global MAX_LOG_LINES
        MAX_LOG_LINES = height - 4

        menu_win = curses.newwin(height - 1, menu_width, 0, 0)
        log_win = curses.newwin(height - 1, log_width, 0, menu_width + 1)
        border_win = curses.newwin(height - 1, 1, 0, menu_width)
        border_win.vline(0, 0, curses.ACS_VLINE, height - 1)
        border_win.refresh()

        menu_win.keypad(True)
        log_win.timeout(100)

        while True:
            new_height, new_width = stdscr.getmaxyx()
            if new_height != height or new_width != width:
                break

            menu_win.erase()
            menu_win.box()
            menu_win.addstr(1, 1, " SCHOOL BUS SERVER MENU ", curses.A_BOLD | curses.A_STANDOUT)
            menu_win.addstr(3, 2, "MANAGE DATABASE", curses.A_UNDERLINE)
            menu_win.addstr(4, 4, "1. Add New Student")
            menu_win.addstr(5, 4, "2. Delete Existing Student")
            menu_win.addstr(6, 4, "3. View All Students")
            menu_win.addstr(7, 4, "4. Clear Entire Database")
            menu_win.addstr(9, 2, "LIVE OPERATIONS", curses.A_UNDERLINE)
            menu_win.addstr(10, 4, "5. Search Students")
            menu_win.addstr(11, 4, "6. Ping a Bus")
            menu_win.addstr(12, 4, "7. Bus Roster by ID")
            menu_win.addstr(13, 4, "8. Exit Program")
            menu_win.addstr(height - 3, 2, "Select option (1-8): _")
            menu_win.refresh()

            log_win.erase()
            log_win.box()
            log_win.addstr(1, 1, " SERVER ACTIVITY LOGS ", curses.A_BOLD)
            while not server_logs.empty():
                new_log = server_logs.get()
                LOG_HISTORY.append(new_log)
                if len(LOG_HISTORY) > MAX_LOG_LINES:
                    LOG_HISTORY.pop(0)
            for i, line in enumerate(LOG_HISTORY[-MAX_LOG_LINES:], 3):
                try:
                    log_line = safe_truncate(line, log_width - 4)
                    if "✅" in line or "🟢" in line:
                        log_win.addstr(i, 2, log_line, curses.color_pair(1))
                    elif "❌" in line or "🔴" in line:
                        log_win.addstr(i, 2, log_line, curses.color_pair(2))
                    else:
                        log_win.addstr(i, 2, log_line)
                except curses.error:
                    pass
            log_win.noutrefresh()
            curses.doupdate()

            menu_win.timeout(100)
            c = menu_win.getch()
            if c != -1:
                if c == ord('1'):
                    menu_win.timeout(-1)
                    add_student(menu_win)
                elif c == ord('2'):
                    menu_win.timeout(-1)
                    delete_student(menu_win)
                elif c == ord('3'):
                    menu_win.timeout(-1)
                    view_all_students(menu_win)
                elif c == ord('4'):
                    menu_win.timeout(-1)
                    clear_all_students(menu_win)
                elif c == ord('5'):
                    menu_win.timeout(-1)
                    search_student(menu_win)
                elif c == ord('6'):
                    menu_win.timeout(-1)
                    ping_bus(menu_win)
                elif c == ord('7'):
                    menu_win.timeout(-1)
                    bus_roll_query(menu_win)
                elif c == ord('8'):
                    return    

# Entry point of the application.
# Starts the server in a background thread and launches the curses UI.

def main():
    server_thread = threading.Thread(target=start_server_thread, daemon=True)
    server_thread.start()
    curses.wrapper(curses_main)

if __name__ == "__main__":
    main()
