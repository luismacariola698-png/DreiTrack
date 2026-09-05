DreiTrack

DreiTrack is a private physical inventory, procurement, asset, and operations management platform built for organizations that manage real-world stock and equipment.

It began as an internship-inspired inventory project and has since been redesigned into a more general system that can support different companies and operational environments.

DreiTrack combines deterministic inventory logic with Drei, a locally hosted AI inventory assistant powered through Ollama.

Project status: Work in progress / portfolio project.
DreiTrack v0.3 is not yet intended to be treated as production-ready commercial software.

Why DreiTrack?

Physical inventory management is more than knowing how many items are on a shelf.

Organizations may also need to track:

stock entering and leaving inventory

purchase orders and supplier deliveries

stock requests and approvals

assets that use inventory components

storage locations and sites

audit adjustments

low-stock risks

unusual inventory activity

employee access and permissions

DreiTrack was built to bring these workflows into one system while keeping the database and deterministic application logic as the source of truth.

Key Features

Inventory Management

Create and manage inventory items

Track available stock

Record stock IN, OUT, and ADJUSTMENT movements

Maintain movement history

Support audit corrections

Track minimum stock levels

Review inventory planning information

Procurement

Create purchase orders

Track ordered and received quantities

Record supplier deliveries

Monitor outstanding stock

Identify overdue purchase orders

Use supplier lead-time information in inventory planning

Requests and Approvals

Create stock requests

Approve or reject requests

Collect approved inventory

Associate requests with assets when required

Preserve request history

Assets

DreiTrack uses a general Asset model instead of being tied to one industry.

Assets may include:

robots

CNC machines

vehicles

3D printers

production lines

test rigs

laboratory equipment

electrical equipment

tooling

other company-defined equipment

Inventory items can be assigned as components of tracked assets.

Sites and Storage Locations

Organizations can structure inventory around physical locations such as:

headquarters

factories

workshops

laboratories

stockrooms

service bays

shelves

parts cages

Inventory can be transferred between storage locations while preserving the organization-wide stock total.

User Accounts and Roles

DreiTrack supports role-based access through:

ADMIN

MANAGER

STAFF

VIEWER

Administrators can create and manage company users.

The private-company build follows:

One DreiTrack installation
        ↓
One company
        ↓
Company administrator
        ↓
Administrator-managed users

Public organization registration is not used in this version.

Drei — Local Inventory Intelligence

Drei is the local AI assistant built into DreiTrack.

Drei runs through Ollama and is designed to explain verified inventory and operations data.

Examples of questions Drei can help with include:

Why is this item's stock low?

What currently needs attention?

Which purchase orders are overdue?

What changed in inventory recently?

Which inventory activity may require review?

Important Design Principle

Drei is not the source of truth.

The database and deterministic application logic remain authoritative.

Drei does not silently:

change stock

create inventory transactions

approve requests

receive purchase orders

create suppliers

modify assets

alter audit records

Drei receives bounded, verified context from DreiTrack and explains that information.

This separation is intentional so that AI-generated text cannot directly change operational inventory records.

Technology Stack

Python

FastAPI

SQLAlchemy

Jinja2

SQLite

Ollama

Qwen-based local model

HTML / CSS

Windows launcher scripts

Project Structure

DreiTrack/
│
├── app/
│   ├── ai/
│   │   ├── agent.py
│   │   ├── activity_agent.py
│   │   ├── activity_tools.py
│   │   ├── config.py
│   │   ├── context.py
│   │   ├── local_model.py
│   │   └── tools.py
│   │
│   ├── static/
│   ├── templates/
│   ├── database.py
│   ├── insights.py
│   ├── main.py
│   ├── models.py
│   ├── services.py
│   └── seed.py
│
├── ollama/
│   └── Modelfile
│
├── Setup DreiTrack.bat
├── DreiTrack.vbs
├── Enable Auto Start.vbs
├── Disable Auto Start.vbs
├── launcher.py
├── smoke_test.py
├── requirements.txt
└── README.md

The exact file structure may evolve as the project is refactored.

First-Time Installation

Requirements

You will need:

Windows

Python 3

Git, if cloning the repository

Ollama, if you want to use Drei

Clone the repository:

git clone https://github.com/luismacariola698-png/DreiTrack.git
cd DreiTrack

Option 1 — Windows Setup Helper

Run:

Setup DreiTrack.bat

The setup helper creates a Python virtual environment, installs the required Python packages, and runs the project smoke test.

After the one-time installation, normal users do not need to manually start DreiTrack from a terminal.

Option 2 — Manual Development Setup

Create a virtual environment:

python -m venv .venv

Activate it:

Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1

Install dependencies:

python -m pip install -r requirements.txt

Run the smoke test:

python smoke_test.py

Start the development server:

python -m uvicorn app.main:app --reload

Open:

http://127.0.0.1:8000

First-Time Company Setup

DreiTrack does not ship with a public default administrator password.

On a fresh database, the application redirects to:

/setup

The first administrator creates:

the company name

administrator name

administrator email

administrator password

DreiTrack then creates the first company and administrator account.

After setup is complete, the setup flow is locked and normal users must log in.

Additional employee accounts are created by an administrator.

This means a public copy of the repository does not need to contain shared demo credentials.

Setting Up Drei

Drei requires Ollama to be installed on the machine running DreiTrack.

After installing Ollama, build the local Drei model from the included Modelfile:

ollama create dreitrack-ai:1.0 -f .\ollama\Modelfile

Check that it exists:

ollama list

You should see:

dreitrack-ai:1.0

Test the model:

ollama run dreitrack-ai:1.0

DreiTrack's normal inventory functionality is designed to remain usable even when the local AI service is unavailable.

Starting DreiTrack Without a Terminal

After the one-time installation, launch:

DreiTrack.vbs

The launcher is designed to:

check whether Ollama is available

start Ollama when possible

start the FastAPI/Uvicorn application

wait for DreiTrack to become available

open the application in the browser

This allows normal use without manually typing development commands into PowerShell.

Optional Windows auto-start helpers are also included.

Security and Privacy Approach

DreiTrack is intended to be a private company system, not an openly accessible public inventory service.

The project currently includes concepts such as:

authenticated access

role-based permissions

organization-scoped records

password hashing

private single-company setup

local AI processing

read-only AI access to operational data

local database and secret files excluded from Git

Files That Should Never Be Committed

The repository .gitignore should exclude local files such as:

.venv/
dreitrack.db
*.db
.env
.dreitrack_session_secret
logs/
__pycache__/

Never publish a real company's inventory database, credentials, API keys, session secrets, or confidential operational data.

Current Limitations

DreiTrack is still under active development.

Before using it as production software for sensitive company operations, further work is planned around:

CSRF protection

stronger audit logging

PostgreSQL

Alembic database migrations

concurrency-safe inventory transactions

database backups and recovery

production HTTPS configuration

stronger authentication controls

deployment hardening

expanded automated testing

The current release should be treated as a learning, development, and portfolio milestone rather than finished commercial software.

Roadmap

Planned areas of development include:

private company network deployment

HTTPS / VPN-based remote access

barcode and QR-code workflows

improved audit trails

supplier analytics

richer dashboards

low-stock and operational alerts

asset maintenance history

CSV / spreadsheet imports and exports

PostgreSQL migration

additional Drei read-only tools

stronger security and test coverage

Design Philosophy

A core principle behind DreiTrack is:

AI should help people understand operational data without replacing the systems that make authoritative inventory decisions.

DreiTrack therefore keeps inventory calculations and database operations deterministic, while using Drei as an explanation and decision-support layer.

Background

DreiTrack began as an idea inspired by real inventory and procurement work during an engineering internship.

The original project was much more specific to one robotics environment. As development continued, it was redesigned into a broader platform for organizations that manage physical inventory and assets.

The project has been a practical way to learn about:

backend development

database architecture

inventory systems

procurement workflows

authentication

authorization

AI integration

deployment

debugging

security considerations

software design and refactoring

Disclaimer

DreiTrack is an independent personal portfolio and learning project.

It is not affiliated with or endorsed by any former employer or third-party organization.

Any demo names, inventory records, organizations, suppliers, assets, users, and transaction data should be fictional or non-confidential.

DreiTrack v0.3 is not represented as production-ready commercial inventory software.

Version

Current public milestone:

DreiTrack v0.3
Private Company Platform

Future releases will continue to expand deployment, security, reliability, and operational capabilities.
