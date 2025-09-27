# Overview

This is a Telegram bot for a home appliance service center that manages customer service orders with role-based access control. The bot allows dispatchers to create and edit service orders while enabling service masters to view, accept, and update order statuses. The system includes features for client history tracking, automatic warranty detection, and real-time notifications between team members.

## Recent Changes (Aug 8, 2025)
- ✅ Bot successfully implemented and running
- ✅ Database initialized with sample users (needs real Telegram user IDs)
- ✅ BOT_TOKEN configured and bot connected to Telegram API
- ✅ All import issues resolved with python-telegram-bot v20.6
- ✅ Role-based authorization system working
- ✅ Order management workflow implemented
- ✅ Notification system with inline keyboards functional
- ✅ User database updated with real Telegram ID (1054693407) as dispatcher

## Critical Fixes Completed (Aug 8, 2025)
- ✅ FIXED: Order acceptance notifications - Masters receive confirmation, dispatchers get notified
- ✅ FIXED: Status change notifications - "To Service" and "Complete" buttons notify dispatchers
- ✅ FIXED: Order creation cancellation - Cancel buttons at every step with proper state cleanup
- ✅ FIXED: Edit Order functionality with field editing and master notifications
- ✅ FIXED: Database transactions with error handling and rollback support
- ✅ FIXED: Message deletion fallback for notification cleanup
- ✅ FIXED: Callback query error handling for expired queries
- ✅ FIXED: Comprehensive error logging for all handlers
- ✅ FIXED: Atomic transactions for all database operations
- ✅ FIXED: Master notifications for THEIR assigned order modifications with field details
- ✅ FIXED: Modified status orders now show Accept button (same functionality as New orders)
- ✅ FIXED: "Message to edit not found" errors with comprehensive fallback handling
- ✅ IMPLEMENTED: Comprehensive master menu system with status management capabilities
- ✅ IMPLEMENTED: Comprehensive dispatcher menu system with order management and create request functionality
- ✅ IMPLEMENTED: Order cancellation (Cancelled status) through dispatcher interface
- ✅ FIXED: Missing /all_orders command registration (critical dispatcher menu access)
- ✅ IMPLEMENTED: Comprehensive /help command with role-specific instructions
- ✅ ENHANCED: /start command with complete menu information and available commands
- ✅ FIXED: "Create Request" button in dispatcher menu - now properly starts order creation workflow
- ✅ INTEGRATED: Create Request button with ConversationHandler for seamless order creation
- ✅ ADDED: "Guarantee" status display in dispatcher menu for existing customer orders
- ✅ UPDATED: Help documentation to include all manageable order statuses (New, Guarantee, In Progress, Service, Modified)

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Bot Framework Architecture
- Built using python-telegram-bot v20.x library for Telegram API integration
- Conversation-based interaction flow using ConversationHandler for multi-step order creation
- State management for tracking user input progress through predefined conversation states

## Authorization System
- White-list based access control using SQLite database
- Role-based permissions with two user types: 'dispatcher' and 'master'
- User validation on bot startup with access denial for unauthorized users
- Telegram user ID as primary authentication mechanism

## Data Storage Design
- SQLite database for local data persistence
- Users table storing Telegram IDs, roles, and user information
- Orders table with auto-incrementing IDs and comprehensive order tracking fields
- Phone number validation using regex patterns for data integrity

## Notification Architecture
- Real-time order notifications to all masters when new orders are created
- Modified order notifications specifically to assigned masters
- Inline keyboard interfaces for interactive order management
- Notification ID tracking for message updates and status synchronization

## Order Management Workflow
- Sequential input collection with validation at each step
- Automatic warranty status detection based on client phone number history
- Status-driven workflow with transitions: New → In Progress → Service → Completed/Cancelled
- Edit functionality with change tracking and re-notification system
- Interactive menu systems for both masters and dispatchers with role-specific capabilities
- Master menu: Status management for In Progress, Service, Modified orders
- Dispatcher menu: Full order management, editing, cancellation, and order creation

# External Dependencies

## Core Libraries
- python-telegram-bot v20.x - Telegram Bot API wrapper
- sqlite3 - Built-in Python SQLite database interface
- logging - Python standard logging framework
- datetime - Date and time handling
- re - Regular expressions for phone number validation
- json - JSON data serialization
- os - Operating system interface

## Database
- SQLite - Local file-based database for user management and order storage
- No external database server required - uses service_center.db file

## Telegram Integration
- Telegram Bot API - For bot communication and user interaction
- Requires BOT_TOKEN environment variable for authentication
- Uses webhook or polling for receiving updates from Telegram servers