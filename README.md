# Smart Sports Meetup and Community Management Platform

This is a web-based sports meetup management system developed for the BMSE3343 Agile Software Development assignment. The system allows users to register as participants or organizers, create sports meetups, view active meetups, manage RSVP, and view user profiles.

## Technologies Used

- Python
- Flask
- Firebase Firestore
- HTML
- CSS
- Pytest
- GitHub Actions

## Main Features

- User registration for participants and organizers
- Login and logout session handling
- Organizer can create sports meetups
- Participant can view active meetups
- Participant can RSVP for meetups
- System prevents duplicate RSVP
- System prevents joining full meetups
- Participant can view other participant profiles
- Participant can view organizer profiles
- Organizer can view participant profiles
- Organizer can view other organizer profiles
- Automated testing using Pytest

## Project Structure

```text
digital-sports-meetup/
├── app.py
├── requirements.txt
├── static/
│   └── style.css
├── templates/
│   └── HTML pages
├── tests/
│   └── pytest test files
└── README.md
