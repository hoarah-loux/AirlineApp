# AirlineApp ✈️

**An airline management system for managing flights, passengers, aircraft, and flight operations.**

AirlineApp is a full-stack airline management application built with Django and React. It provides a centralized system for managing flight information, airport data, aircraft configurations, passengers, tickets, and flight crew.

The project also implements an automated roster generation engine that handles crew selection, passenger seating assignments, and flight-specific menu generation.

## Features

- **Flight Management:** Create, update, search, and manage flights and their operational information.
- **Airport Management:** Maintain airport information, including IATA-style airport codes, cities, and countries.
- **Aircraft Management:** Manage aircraft types, seating configurations, capacity, and crew requirements.
- **Passenger Management:** Maintain passenger records, ticket associations, and passenger relationships.
- **Ticket Management:** Manage flight tickets, ticket classes, and seat assignments.
- **Crew Management:** Maintain pilot and cabin crew records, qualifications, and restrictions.
- **Automatic Roster Generation:** Automatically assign eligible pilots and cabin crew according to operational requirements.
- **Seat Allocation:** Generate passenger seating assignments while considering seating classes and affiliated passengers.
- **Menu Generation:** Generate flight menus based on aircraft configurations and available cabin chefs.
- **REST API:** Expose application functionality through Django REST Framework.
- **Authentication:** JWT-based authentication and role-based permissions.

## Technology Stack

| Technology | Purpose |
|---|---|
| Python & Django | Backend application |
| Django REST Framework | REST API |
| React | Frontend |
| Vite | Frontend development and build |
| SQLite | Primary relational database |
| MongoDB | NoSQL roster storage |
| Docker Compose | MongoDB deployment |
| JWT | Authentication |
| Axios | Frontend API communication |

## Architecture

AirlineApp follows a client-server architecture.

- **Frontend:** React-based interface for interacting with airline operations.
- **Backend:** Django application responsible for business logic, validation, and API endpoints.
- **SQL Database:** Stores structured airline information and operational records.
- **NoSQL Database:** Supports alternative storage of generated roster payloads.

The application supports both SQL and NoSQL storage backends for generated flight rosters.

## Getting Started

### Prerequisites

- Python 3.10+
- Node.js and npm
- Docker and Docker Compose (for MongoDB functionality)

### 1. Clone the Repository

```bash
git clone https://github.com/hoarah-loux/AirlineApp.git
cd AirlineApp
```

### 2. Set Up the Backend

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

### 3. Set Up the Frontend

In a separate terminal:

```bash
cd frontend
npm install
npm run dev
```

### 4. Start MongoDB

For NoSQL roster storage:

```bash
docker compose up -d
```

The Django backend runs at `http://127.0.0.1:8000`, while the frontend runs using the Vite development server.

## Project Structure

```text
AirlineApp/
├── airline_app/       # Django project configuration
├── flights/           # Core airline application
├── frontend/          # React frontend
├── migrations/        # Database migrations
├── templates/         # Django templates
├── docker-compose.yml # MongoDB configuration
├── manage.py
└── requirements.txt
```

## Future Work

- Expand flight scheduling and operational management.
- Improve roster generation and crew allocation.
- Enhance passenger booking and ticket management.
- Extend reporting and operational analytics.
- Improve frontend functionality and user experience.

## License

See the repository for licensing information.
