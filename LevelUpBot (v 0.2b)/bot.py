
#!/usr/bin/env python3
"""
Telegram Bot for Home Appliance Service Center
Handles order management with role-based authorization
"""

import os
import json
import re
import sqlite3
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        Application, CommandHandler, CallbackQueryHandler, MessageHandler,
        ContextTypes, ConversationHandler, filters
    )
except ImportError:
    print("Error: python-telegram-bot library not properly installed.")
    print("Please run: pip install python-telegram-bot==20.6")
    exit(1)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Database file
DB_FILE = 'service_center.db'

# Phone validation regex
PHONE_PATTERN = re.compile(r'^\+7\d{10}$')

# Conversation states
(PHONE, CLIENT_NAME, ADDRESS, DEVICE_TYPE, PROBLEM_SHORT, 
 PROBLEM_FULL, ADDITIONAL_INFO, EDIT_FIELD, EDIT_VALUE,
 COMPLETION_AMOUNT, COMPLETION_DOCUMENT, COMPLETION_ADDITIONAL) = range(12)

class ServiceBot:
    def __init__(self):
        self.init_database()
    
    def init_database(self):
        """Initialize SQLite database with required tables"""
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Create users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                role TEXT NOT NULL CHECK (role IN ('dispatcher', 'master')),
                full_name TEXT
            )
        ''')
        
        # Create orders table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT DEFAULT 'New' CHECK (status IN ('New', 'Guarantee', 'Modified', 'In Progress', 'Service', 'Completed')),
                client_phone TEXT NOT NULL,
                client_name TEXT NOT NULL,
                client_address TEXT NOT NULL,
                device_type TEXT NOT NULL,
                problem_short TEXT NOT NULL,
                problem_full TEXT,
                additional_info TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                master_id INTEGER REFERENCES users(user_id),
                notification_ids TEXT,
                completion_amount REAL,
                completion_document TEXT,
                completion_additional TEXT
            )
        ''')
        
        # Add new columns if they don't exist (for existing databases)
        try:
            cursor.execute('ALTER TABLE orders ADD COLUMN completion_amount REAL')
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute('ALTER TABLE orders ADD COLUMN completion_document TEXT')
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute('ALTER TABLE orders ADD COLUMN completion_additional TEXT')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
    
    def get_user_role(self, user_id: int) -> Optional[str]:
        """Get user role from database"""
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT role FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    
    def get_user_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get full user information"""
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, role, full_name FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        if result:
            return {'user_id': result[0], 'role': result[1], 'full_name': result[2]}
        return None
    
    def get_all_masters(self) -> List[int]:
        """Get all master user IDs"""
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE role = 'master'")
        masters = [row[0] for row in cursor.fetchall()]
        conn.close()
        return masters
    
    def check_previous_orders(self, phone: str) -> bool:
        """Check if phone number has previous orders"""
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM orders WHERE client_phone = ?", (phone,))
        count = cursor.fetchone()[0]
        conn.close()
        return count > 0
    
    def create_order(self, order_data: Dict[str, Any]) -> int:
        """Create new order and return order ID"""
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Check if previous orders exist to determine status
        has_previous = self.check_previous_orders(order_data['client_phone'])
        status = "Guarantee" if has_previous else "New"
        
        cursor.execute('''
            INSERT INTO orders (status, client_phone, client_name, client_address,
                              device_type, problem_short, problem_full, additional_info)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            status, order_data['client_phone'], order_data['client_name'],
            order_data['client_address'], order_data['device_type'],
            order_data['problem_short'], order_data.get('problem_full'),
            order_data.get('additional_info')
        ))
        
        order_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        logger.info(f"Created new order #{order_id} with status '{status}'")
        return order_id
    
    def get_order(self, order_id: int) -> Optional[Dict[str, Any]]:
        """Get order by ID"""
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, status, client_phone, client_name, client_address,
                   device_type, problem_short, problem_full, additional_info,
                   created_at, updated_at, master_id, notification_ids,
                   completion_amount, completion_document, completion_additional
            FROM orders WHERE id = ?
        ''', (order_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {
                'id': result[0], 'status': result[1], 'client_phone': result[2],
                'client_name': result[3], 'client_address': result[4],
                'device_type': result[5], 'problem_short': result[6],
                'problem_full': result[7], 'additional_info': result[8],
                'created_at': result[9], 'updated_at': result[10],
                'master_id': result[11], 'notification_ids': result[12],
                'completion_amount': result[13], 'completion_document': result[14],
                'completion_additional': result[15]
            }
        return None
    
    def update_order(self, order_id: int, updates: Dict[str, Any], set_modified: bool = False):
        """Update order fields with transaction support"""
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        try:
            # Build update query
            fields = []
            values = []
            for key, value in updates.items():
                fields.append(f"{key} = ?")
                values.append(value)
            
            if set_modified:
                fields.append("status = ?")
                values.append("Modified")
            
            fields.append("updated_at = CURRENT_TIMESTAMP")
            values.append(order_id)
            
            query = f"UPDATE orders SET {', '.join(fields)} WHERE id = ?"
            cursor.execute(query, values)
            conn.commit()
            logger.info(f"Updated order #{order_id}")
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error updating order #{order_id}: {e}")
            raise
        finally:
            conn.close()
    
    def get_master_orders(self, master_id: int) -> List[Dict[str, Any]]:
        """Get orders assigned to a master"""
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, status, client_name, device_type, problem_short, created_at
            FROM orders WHERE master_id = ? ORDER BY created_at DESC
        ''', (master_id,))
        
        orders = []
        for row in cursor.fetchall():
            orders.append({
                'id': row[0], 'status': row[1], 'client_name': row[2],
                'device_type': row[3], 'problem_short': row[4], 'created_at': row[5]
            })
        
        conn.close()
        return orders
    
    def get_master_closed_orders(self, master_id: int) -> List[Dict[str, Any]]:
        """Get completed orders assigned to a master"""
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, client_phone, client_name, device_type, problem_short, 
                   completion_amount, completion_document, completion_additional, 
                   created_at, updated_at
            FROM orders 
            WHERE master_id = ? AND status = 'Completed' 
            ORDER BY updated_at DESC
        ''', (master_id,))
        
        orders = []
        for row in cursor.fetchall():
            orders.append({
                'id': row[0], 'client_phone': row[1], 'client_name': row[2],
                'device_type': row[3], 'problem_short': row[4], 
                'completion_amount': row[5], 'completion_document': row[6],
                'completion_additional': row[7], 'created_at': row[8], 'updated_at': row[9]
            })
        
        conn.close()
        return orders
    
    async def delete_notifications(self, order_id: int, context: ContextTypes.DEFAULT_TYPE):
        """Delete notifications for all masters with error handling"""
        order = self.get_order(order_id)
        if not order or not order['notification_ids']:
            return
        
        try:
            notification_data = json.loads(order['notification_ids'])
            for chat_id, message_id in notification_data.items():
                try:
                    await context.bot.delete_message(chat_id=int(chat_id), message_id=message_id)
                    logger.info(f"Deleted notification message {message_id} from chat {chat_id}")
                except Exception as e:
                    # Ignore MessageToDeleteNotFound and similar errors
                    if "message to delete not found" not in str(e).lower():
                        logger.warning(f"Failed to delete message {message_id} from {chat_id}: {e}")
            
            # Clear notification IDs
            self.update_order(order_id, {'notification_ids': None})
            
        except Exception as e:
            logger.error(f"Error deleting notifications for order #{order_id}: {e}")
    
    async def notify_masters(self, order_id: int, context: ContextTypes.DEFAULT_TYPE, is_modified: bool = False):
        """Send notifications to all masters about new/modified order"""
        order = self.get_order(order_id)
        if not order:
            return
        
        masters = self.get_all_masters()
        notification_ids = {}
        
        if is_modified:
            text = f"🛠 Изменённая заявка #{order_id}. Посмотреть изменения?"
            keyboard = [
                [InlineKeyboardButton("Да", callback_data=f"view_order_{order_id}"),
                 InlineKeyboardButton("Нет", callback_data="ignore")]
            ]
        else:
            text = f"🚨 Новая заявка: #{order_id}\n• {order['device_type']}\n• {order['problem_short']}"
            keyboard = [[InlineKeyboardButton("Подробности", callback_data=f"view_order_{order_id}")]]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        for master_id in masters:
            try:
                message = await context.bot.send_message(
                    chat_id=master_id,
                    text=text,
                    reply_markup=reply_markup
                )
                notification_ids[str(master_id)] = message.message_id
                logger.info(f"Sent notification to master {master_id} for order #{order_id}")
            except Exception as e:
                logger.error(f"Failed to send notification to master {master_id}: {e}")
        
        # Store notification IDs
        if notification_ids:
            self.update_order(order_id, {'notification_ids': json.dumps(notification_ids)})

# Initialize bot instance
service_bot = ServiceBot()

# Authorization decorator
def require_role(required_role: str):
    def decorator(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_id = update.effective_user.id
            user_role = service_bot.get_user_role(user_id)
            
            if user_role != required_role:
                if user_role is None:
                    await update.message.reply_text("❌ Доступ запрещён. Вы не авторизованы для использования этого бота.")
                else:
                    await update.message.reply_text(f"❌ Доступ запрещён. Эта команда доступна только для {required_role}.")
                return
            
            return await func(update, context)
        return wrapper
    return decorator

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user_id = update.effective_user.id
    user_info = service_bot.get_user_info(user_id)
    
    if not user_info:
        await update.message.reply_text("❌ Доступ запрещён. Вы не авторизованы для использования этого бота.")
        logger.warning(f"Unauthorized access attempt from user {user_id}")
        return
    
    role = user_info['role']
    name = user_info['full_name'] or "Пользователь"
    
    welcome_message = f"👋 Добро пожаловать, {name}!\n\nВаша роль: {role.title()}\n\n"
    
    if role == 'dispatcher':
        welcome_message += (
            "📋 Доступные команды:\n"
            "/all_orders - Интерактивное меню диспетчера\n"
            "/new_order - Создать новую заявку\n"
            "/edit_order [ID] - Редактировать заявку\n"
            "/help - Показать справку"
        )
    elif role == 'master':
        welcome_message += (
            "🛠 Доступные команды:\n"
            "/my_orders - Интерактивное меню мастера\n"
            "/closed_orders - Закрытые заявки\n"
            "/help - Показать справку"
        )
    
    await update.message.reply_text(welcome_message)
    logger.info(f"User {user_id} ({role}) accessed the bot")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command handler"""
    user_id = update.effective_user.id
    user_info = service_bot.get_user_info(user_id)
    
    if not user_info:
        await update.message.reply_text(
            "❌ Доступ запрещён. Пожалуйста, обратитесь к администратору для получения доступа."
        )
        return
    
    role = user_info['role']
    
    help_message = "🤖 **Справка по Telegram боту сервисного центра**\n\n"
    
    if role == 'dispatcher':
        help_message += (
            "📋 **Команды диспетчера:**\n"
            "/all_orders - Интерактивное меню для просмотра и управления всеми заявками\n"
            "   • Просмотр деталей заявки (имя, телефон, адрес, техника, проблема, мастер)\n"
            "   • Редактирование информации заявки без ввода команд\n"
            "   • Отмена заявок (установка статуса 'Отменено')\n"
            "   • Создание новых заявок прямо из меню\n\n"
            "/new_order - Создать новую заявку (пошагово)\n"
            "/edit_order [ID] - Редактировать конкретную заявку по ID\n"
            "/start - Показать приветственное сообщение\n"
            "/help - Показать эту справку\n\n"
            "📊 **Статусы заявок, которыми вы можете управлять:**\n"
            "• New, Guarantee, In Progress, Service, Modified\n"
            "• Можете отменить любую заявку (устанавливает статус 'Отменено')"
        )
    elif role == 'master':
        help_message += (
            "🛠 **Команды мастера:**\n"
            "/my_orders - Интерактивное меню для ваших назначенных заявок\n"
            "   • Просмотр заявок со статусом: В работе, В сервисе, Изменено\n"
            "   • Изменение статусов заявок на основе текущего состояния:\n"
            "     - В работе → В сервис или Завершено\n"
            "     - В сервисе → Завершено\n"
            "     - Изменено → В работе, В сервис или Завершено\n\n"
            "/closed_orders - Просмотр ваших завершённых заявок\n"
            "/start - Показать приветственное сообщение\n"
            "/help - Показать эту справку\n\n"
            "🔄 **Управление статусами:**\n"
            "• Вы получаете уведомления, когда диспетчеры изменяют ваши заявки\n"
            "• Диспетчеры уведомляются при изменении статусов ваших заявок"
        )
    
    help_message += "\n\n💡 **Советы:**\n• Используйте интерактивные меню для удобной навигации\n• Все изменения регистрируются и отслеживаются\n• Уведомления в реальном времени держат всех в курсе"
    
    await update.message.reply_text(help_message)

@require_role('dispatcher')
async def new_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start new order creation process"""
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_new_order")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📋 Creating new order...\n\n📞 Please enter client phone number (format: +7XXXXXXXXXX):\n\n💡 Use /cancel to stop at any time",
        reply_markup=reply_markup
    )
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Validate and store phone number"""
    phone = update.message.text.strip()
    
    if not PHONE_PATTERN.match(phone):
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_new_order")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "❌ Invalid phone format. Please use +7XXXXXXXXXX format:\n\n💡 Use /cancel to stop",
            reply_markup=reply_markup
        )
        return PHONE
    
    context.user_data['order_data'] = {'client_phone': phone}
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_new_order")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👤 Please enter client name:\n\n💡 Use /cancel to stop",
        reply_markup=reply_markup
    )
    return CLIENT_NAME

async def get_client_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store client name"""
    context.user_data['order_data']['client_name'] = update.message.text.strip()
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_new_order")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "📍 Please enter client address:\n\n💡 Use /cancel to stop",
        reply_markup=reply_markup
    )
    return ADDRESS

async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store address"""
    context.user_data['order_data']['client_address'] = update.message.text.strip()
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_new_order")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🔧 Please enter appliance type:\n\n💡 Use /cancel to stop",
        reply_markup=reply_markup
    )
    return DEVICE_TYPE

async def get_device_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store device type"""
    context.user_data['order_data']['device_type'] = update.message.text.strip()
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_new_order")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "⚠️ Please enter short problem description:\n\n💡 Use /cancel to stop",
        reply_markup=reply_markup
    )
    return PROBLEM_SHORT

async def get_problem_short(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store short problem description"""
    context.user_data['order_data']['problem_short'] = update.message.text.strip()
    keyboard = [
        [InlineKeyboardButton("⏭️ Пропустить", callback_data="skip_problem_full")],
        [InlineKeyboardButton("❌ Отменить", callback_data="cancel_new_order")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "📝 Please enter full problem description:\n\n💡 Use /skip or the button below",
        reply_markup=reply_markup
    )
    return PROBLEM_FULL

async def get_problem_full(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store full problem description"""
    text = update.message.text.strip()
    if text != '/skip':
        context.user_data['order_data']['problem_full'] = text
    
    keyboard = [
        [InlineKeyboardButton("⏭️ Пропустить", callback_data="skip_additional_info")],
        [InlineKeyboardButton("❌ Отменить", callback_data="cancel_new_order")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "ℹ️ Please enter additional information:\n\n💡 Use /skip or the button to finish",
        reply_markup=reply_markup
    )
    return ADDITIONAL_INFO

async def get_additional_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store additional info and create order"""
    text = update.message.text.strip()
    if text != '/skip':
        context.user_data['order_data']['additional_info'] = text
    
    return await complete_order_creation(update, context)

# Completion wizard handlers
async def get_completion_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get completion amount from master"""
    text = update.message.text.strip()
    
    try:
        amount = float(text)
        if amount < 0:
            await update.message.reply_text("❌ Сумма не может быть отрицательной. Введите корректную сумму:")
            return COMPLETION_AMOUNT
    except ValueError:
        await update.message.reply_text("❌ Введите числовое значение суммы (например: 1500.50):")
        return COMPLETION_AMOUNT
    
    # Store amount
    context.user_data['completion_amount'] = amount
    
    # Ask about document
    keyboard = [
        [InlineKeyboardButton("✅ Да", callback_data="completion_document_yes")],
        [InlineKeyboardButton("❌ Нет", callback_data="completion_document_no")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📄 Оставлен ли документ клиенту?",
        reply_markup=reply_markup
    )
    
    return COMPLETION_DOCUMENT

async def get_completion_additional(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get additional completion information from master"""
    text = update.message.text.strip()
    
    # Store additional info
    context.user_data['completion_additional'] = text
    
    return await finalize_completion(update, context)

async def finalize_completion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finalize the order completion"""
    order_id = context.user_data['completion_order_id']
    amount = context.user_data['completion_amount']
    document = context.user_data['completion_document']
    additional = context.user_data.get('completion_additional', '')
    
    user_id = update.effective_user.id
    
    # Get master info
    master_info = service_bot.get_user_info(user_id)
    master_name = master_info['full_name'] if master_info else f"Master {user_id}"
    
    # Update order with completion data
    completion_data = {
        'status': 'Completed',
        'completion_amount': amount,
        'completion_document': document,
        'completion_additional': additional if additional else None
    }
    
    service_bot.update_order(order_id, completion_data)
    
    # Send confirmation to master
    confirmation_text = f"✅ Заявка #{order_id} успешно завершена!\n\n"
    confirmation_text += f"💰 Сумма: {amount} руб.\n"
    confirmation_text += f"📄 Документ: {document}\n"
    if additional:
        confirmation_text += f"📝 Доп. информация: {additional}\n"
    
    await update.message.reply_text(confirmation_text)
    
    # Notify dispatchers
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE role = 'dispatcher'")
        dispatchers = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        for dispatcher_id in dispatchers:
            try:
                dispatcher_text = f"✅ Заявка #{order_id} завершена мастером {master_name}\n\n"
                dispatcher_text += f"💰 Сумма: {amount} руб.\n"
                dispatcher_text += f"📄 Документ оставлен: {document}\n"
                if additional:
                    dispatcher_text += f"📝 Доп. информация: {additional}\n"
                
                await context.bot.send_message(
                    chat_id=dispatcher_id,
                    text=dispatcher_text
                )
            except Exception as e:
                logger.error(f"Failed to notify dispatcher {dispatcher_id}: {e}")
    except Exception as e:
        logger.error(f"Error notifying dispatchers about order #{order_id} completion: {e}")
    
    logger.info(f"Order #{order_id} completed by {master_name} with amount {amount}")
    
    # Clear completion data
    completion_keys = ['completion_order_id', 'completion_amount', 'completion_document', 'completion_additional']
    for key in completion_keys:
        context.user_data.pop(key, None)
    
    return ConversationHandler.END

async def finalize_completion_callback(query, context: ContextTypes.DEFAULT_TYPE):
    """Finalize completion from callback query"""
    order_id = context.user_data['completion_order_id']
    amount = context.user_data['completion_amount']
    document = context.user_data['completion_document']
    additional = context.user_data.get('completion_additional', '')
    
    user_id = query.from_user.id
    
    # Get master info
    master_info = service_bot.get_user_info(user_id)
    master_name = master_info['full_name'] if master_info else f"Master {user_id}"
    
    # Update order with completion data
    completion_data = {
        'status': 'Completed',
        'completion_amount': amount,
        'completion_document': document,
        'completion_additional': additional if additional else None
    }
    
    service_bot.update_order(order_id, completion_data)
    
    # Send confirmation to master
    confirmation_text = f"✅ Заявка #{order_id} успешно завершена!\n\n"
    confirmation_text += f"💰 Сумма: {amount} руб.\n"
    confirmation_text += f"📄 Документ: {document}\n"
    if additional:
        confirmation_text += f"📝 Доп. информация: {additional}\n"
    
    try:
        await query.edit_message_text(confirmation_text)
    except Exception as e:
        if "not found" in str(e).lower():
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=confirmation_text
            )
    
    # Notify dispatchers
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE role = 'dispatcher'")
        dispatchers = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        for dispatcher_id in dispatchers:
            try:
                dispatcher_text = f"✅ Заявка #{order_id} завершена мастером {master_name}\n\n"
                dispatcher_text += f"💰 Сумма: {amount} руб.\n"
                dispatcher_text += f"📄 Документ оставлен: {document}\n"
                if additional:
                    dispatcher_text += f"📝 Доп. информация: {additional}\n"
                
                await context.bot.send_message(
                    chat_id=dispatcher_id,
                    text=dispatcher_text
                )
            except Exception as e:
                logger.error(f"Failed to notify dispatcher {dispatcher_id}: {e}")
    except Exception as e:
        logger.error(f"Error notifying dispatchers about order #{order_id} completion: {e}")
    
    logger.info(f"Order #{order_id} completed by {master_name} with amount {amount}")
    
    # Clear completion data
    completion_keys = ['completion_order_id', 'completion_amount', 'completion_document', 'completion_additional']
    for key in completion_keys:
        context.user_data.pop(key, None)
    
    return ConversationHandler.END

async def complete_order_creation(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    """Complete order creation process"""
    try:
        # Create order
        order_data = context.user_data['order_data']
        order_id = service_bot.create_order(order_data)
        
        # Notify masters
        await service_bot.notify_masters(order_id, context)
        
        order = service_bot.get_order(order_id)
        
        # Send confirmation message
        message_text = (
            f"✅ Order #{order_id} created successfully!\n"
            f"Status: {order['status']}\n"
            f"All masters have been notified."
        )
        
        if hasattr(update_or_query, 'message'):  # Regular update
            await update_or_query.message.reply_text(message_text)
        else:  # Callback query
            await context.bot.send_message(
                chat_id=update_or_query.from_user.id,
                text=message_text
            )
        
        # Clear user data
        context.user_data.clear()
        logger.info(f"Order #{order_id} created successfully")
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error creating order: {e}")
        error_text = f"❌ Error creating order: {str(e)}"
        
        if hasattr(update_or_query, 'message'):
            await update_or_query.message.reply_text(error_text)
        else:
            await context.bot.send_message(
                chat_id=update_or_query.from_user.id,
                text=error_text
            )
        
        context.user_data.clear()
        return ConversationHandler.END

async def skip_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /skip command during order creation"""
    return await get_additional_info(update, context)

async def cancel_order_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel order creation via /cancel command"""
    context.user_data.clear()
    await update.message.reply_text("❌ Order creation cancelled")
    logger.info("Order creation cancelled via /cancel command")
    return ConversationHandler.END

@require_role('dispatcher')
async def edit_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /edit_order command"""
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("❌ Please provide order ID: /edit_order [ID]")
        return
    
    order_id = int(context.args[0])
    order = service_bot.get_order(order_id)
    
    if not order:
        await update.message.reply_text(f"❌ Order #{order_id} not found.")
        return
    
    # Display current order data
    order_text = (
        f"📋 Order #{order_id} - Current Data:\n\n"
        f"📞 Phone: {order['client_phone']}\n"
        f"👤 Name: {order['client_name']}\n"
        f"📍 Address: {order['client_address']}\n"
        f"🔧 Device: {order['device_type']}\n"
        f"⚠️ Problem: {order['problem_short']}\n"
        f"📝 Full description: {order['problem_full'] or 'N/A'}\n"
        f"ℹ️ Additional info: {order['additional_info'] or 'N/A'}\n"
        f"📊 Status: {order['status']}"
    )
    
    keyboard = [
        [InlineKeyboardButton("📞 Изменить телефон", callback_data=f"edit_{order_id}_client_phone")],
        [InlineKeyboardButton("👤 Изменить имя", callback_data=f"edit_{order_id}_client_name")],
        [InlineKeyboardButton("📍 Изменить адрес", callback_data=f"edit_{order_id}_client_address")],
        [InlineKeyboardButton("🔧 Изменить устройство", callback_data=f"edit_{order_id}_device_type")],
        [InlineKeyboardButton("⚠️ Изменить проблему", callback_data=f"edit_{order_id}_problem_short")],
        [InlineKeyboardButton("📝 Изменить описание", callback_data=f"edit_{order_id}_problem_full")],
        [InlineKeyboardButton("ℹ️ Изменить доп. инфо", callback_data=f"edit_{order_id}_additional_info")],
        [InlineKeyboardButton("❌ Отменить", callback_data="cancel_edit")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(order_text, reply_markup=reply_markup)

async def handle_edit_field_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle new field value during edit process"""
    if 'edit_order_id' not in context.user_data or 'edit_field' not in context.user_data:
        # No active edit session, just ignore the message
        return
    
    order_id = context.user_data['edit_order_id']
    field = context.user_data['edit_field']
    new_value = update.message.text.strip()
    
    # Validate phone number if editing phone field
    if field == 'client_phone' and not PHONE_PATTERN.match(new_value):
        await update.message.reply_text("❌ Invalid phone format. Please use +7XXXXXXXXXX format:")
        return
    
    try:
        # Update the order field
        service_bot.update_order(order_id, {field: new_value}, set_modified=True)
        
        # Get updated order
        order = service_bot.get_order(order_id)
        if not order:
            await update.message.reply_text(f"❌ Order #{order_id} not found.")
            context.user_data.clear()
            return
        
        # Show updated order details
        order_text = (
            f"✅ Order #{order_id} updated successfully!\n\n"
            f"📞 Phone: {order['client_phone']}\n"
            f"👤 Name: {order['client_name']}\n"
            f"📍 Address: {order['client_address']}\n"
            f"🔧 Device: {order['device_type']}\n"
            f"⚠️ Problem: {order['problem_short']}\n"
            f"📝 Full description: {order['problem_full'] or 'N/A'}\n"
            f"ℹ️ Additional info: {order['additional_info'] or 'N/A'}\n"
            f"📊 Status: {order['status']}"
        )
        
        await update.message.reply_text(order_text)
        
        # Notify assigned master if exists
        if order['master_id']:
            try:
                # Send detailed notification about the modification
                field_names = {
                    'client_phone': 'Phone number',
                    'client_name': 'Client name',
                    'client_address': 'Address',
                    'device_type': 'Device type',
                    'problem_short': 'Problem description',
                    'problem_full': 'Full description',
                    'additional_info': 'Additional info'
                }
                field_display = field_names.get(field, field)
                
                notification_text = (
                    f"🛠 **YOUR** Order #{order_id} has been modified!\n\n"
                    f"📝 Changed field: {field_display}\n"
                    f"🔄 New value: {new_value}\n\n"
                    f"Please review the updated order details."
                )
                
                await context.bot.send_message(
                    chat_id=order['master_id'],
                    text=notification_text
                )
                logger.info(f"Notified assigned master {order['master_id']} about order #{order_id} modification")
            except Exception as e:
                logger.error(f"Failed to notify assigned master {order['master_id']}: {e}")
        
        logger.info(f"Order #{order_id} field '{field}' updated to '{new_value}'")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error updating order: {str(e)}")
        logger.error(f"Error updating order #{order_id}: {e}")
    
    # Clear edit session
    context.user_data.clear()

@require_role('master')
async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show interactive menu of orders assigned to the current master"""
    user_id = update.effective_user.id
    
    # Get orders assigned to this master with relevant statuses
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, client_name, device_type, problem_short, status, created_at 
        FROM orders 
        WHERE master_id = ? AND status IN ('In Progress', 'Service', 'Modified')
        ORDER BY created_at DESC
    """, (user_id,))
    orders = cursor.fetchall()
    conn.close()
    
    if not orders:
        await update.message.reply_text("📋 You have no orders with In Progress, Service, or Modified status.")
        return
    
    # Create inline keyboard with order buttons
    keyboard = []
    for order in orders:
        order_id, client_name, device_type, problem_short, status, created_at = order
        button_text = f"#{order_id} - {status}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"master_order_{order_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "🛠 Меню ваших заявок:\nВыберите заявку для просмотра деталей и управления статусом:"
    
    await update.message.reply_text(text, reply_markup=reply_markup)

@require_role('master')
async def closed_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show closed orders for master with proper navigation"""
    user_id = update.effective_user.id
    
    # Get completed orders for this master
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, client_name, client_phone, device_type, problem_short, created_at, 
               completion_amount, completion_document, completion_additional
        FROM orders 
        WHERE master_id = ? AND status = 'Completed'
        ORDER BY created_at DESC
        LIMIT 20
    """, (user_id,))
    orders = cursor.fetchall()
    conn.close()
    
    if not orders:
        await update.message.reply_text("📋 У вас нет завершённых заявок.")
        return
    
    # Create navigation buttons like regular master menu
    keyboard = []
    for order in orders:
        order_id, client_name, client_phone, device_type, problem_short, created_at, amount, document, additional = order
        # Format button text: "#{ID} | {phone}"
        button_text = f"#{order_id} | {client_phone}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"view_completed_{order_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📋 Ваши завершённые заявки:\n\nВыберите заявку для просмотра деталей:",
        reply_markup=reply_markup
    )

@require_role('dispatcher')
async def all_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show interactive menu of all orders for dispatcher"""
    # Get all orders with relevant statuses (including Guarantee and Completed)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, client_name, device_type, problem_short, status, created_at 
        FROM orders 
        WHERE status IN ('New', 'Guarantee', 'In Progress', 'Service', 'Modified', 'Completed')
        ORDER BY created_at DESC
    """)
    orders = cursor.fetchall()
    conn.close()
    
    if not orders:
        await update.message.reply_text("📋 Заявки не найдены.")
        return
    
    # Create inline keyboard with order buttons and create request button
    keyboard = []
    
    # Add Create Request button at the top
    keyboard.append([InlineKeyboardButton("➕ Создать заявку", callback_data="create_request")])
    
    # Add separator
    if orders:
        keyboard.append([])  # Empty row for separation
    
    for order in orders:
        order_id, client_name, device_type, problem_short, status, created_at = order
        button_text = f"#{order_id} - {status}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"dispatcher_order_{order_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "📋 Меню диспетчера:\nВыберите заявку для просмотра и управления или создайте новую:"
    
    await update.message.reply_text(text, reply_markup=reply_markup)

# Callback query handlers
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all callback queries"""
    query = update.callback_query
    
    try:
        await query.answer()
    except Exception as e:
        # Handle expired callbacks gracefully
        if "too old" in str(e).lower() or "expired" in str(e).lower():
            logger.warning(f"Callback query expired: {e}")
            return
        else:
            logger.error(f"Error answering callback query: {e}")
            return
    
    data = query.data
    
    if data.startswith("master_order_"):
        # Handle master menu order selection
        order_id = int(data.split("_")[2])
        order = service_bot.get_order(order_id)
        
        if not order:
            try:
                await query.edit_message_text("❌ Order not found.")
            except Exception as e:
                if "not found" in str(e).lower():
                    await context.bot.send_message(chat_id=query.from_user.id, text="❌ Order not found.")
            return
        
        # Show order details with status management buttons
        master_name = ""
        if order['master_id']:
            master_info = service_bot.get_user_info(order['master_id'])
            master_name = f"\n👨‍🔧 Master: {master_info['full_name'] if master_info else 'Unknown'}"
        
        order_text = (
            f"🛠 Order #{order_id} Details:\n\n"
            f"📞 Phone: {order['client_phone']}\n"
            f"👤 Name: {order['client_name']}\n"
            f"📍 Address: {order['client_address']}\n"
            f"🔧 Device: {order['device_type']}\n"
            f"⚠️ Problem: {order['problem_short']}\n"
            f"📝 Full description: {order['problem_full'] or 'N/A'}\n"
            f"ℹ️ Additional info: {order['additional_info'] or 'N/A'}{master_name}\n"
            f"📊 Status: {order['status']}\n"
            f"📅 Created: {order['created_at'][:16]}"
        )
        
        keyboard = []
        current_status = order['status']
        
        # Status management buttons based on current status
        if current_status == 'In Progress':
            keyboard.extend([
                [InlineKeyboardButton("🔧 В сервис", callback_data=f"change_status_{order_id}_Service")],
                [InlineKeyboardButton("✅ Завершить", callback_data=f"change_status_{order_id}_Completed")]
            ])
        elif current_status == 'Service':
            keyboard.append([InlineKeyboardButton("✅ Завершить", callback_data=f"change_status_{order_id}_Completed")])
        elif current_status == 'Modified':
            keyboard.extend([
                [InlineKeyboardButton("🔄 В работу", callback_data=f"change_status_{order_id}_In Progress")],
                [InlineKeyboardButton("🔧 В сервис", callback_data=f"change_status_{order_id}_Service")],
                [InlineKeyboardButton("✅ Завершить", callback_data=f"change_status_{order_id}_Completed")]
            ])
        
        # Back to menu button
        keyboard.append([InlineKeyboardButton("⬅️ Назад в меню", callback_data="back_to_master_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.edit_message_text(order_text, reply_markup=reply_markup)
        except Exception as e:
            if "not found" in str(e).lower():
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text=order_text,
                    reply_markup=reply_markup
                )
    
    elif data.startswith("dispatcher_order_"):
        # Handle dispatcher menu order selection
        order_id = int(data.split("_")[2])
        order = service_bot.get_order(order_id)
        
        if not order:
            try:
                await query.edit_message_text("❌ Order not found.")
            except Exception as e:
                if "not found" in str(e).lower():
                    await context.bot.send_message(chat_id=query.from_user.id, text="❌ Order not found.")
            return
        
        # Show order details with management buttons
        master_name = ""
        if order['master_id']:
            master_info = service_bot.get_user_info(order['master_id'])
            master_name = f"\n👨‍🔧 Master: {master_info['full_name'] if master_info else 'Unknown'}"
        
        order_text = (
            f"📋 Order #{order_id} Details:\n\n"
            f"📞 Phone: {order['client_phone']}\n"
            f"👤 Name: {order['client_name']}\n"
            f"📍 Address: {order['client_address']}\n"
            f"🔧 Device: {order['device_type']}\n"
            f"⚠️ Problem: {order['problem_short']}\n"
            f"📝 Full description: {order['problem_full'] or 'N/A'}\n"
            f"ℹ️ Additional info: {order['additional_info'] or 'N/A'}{master_name}\n"
            f"📊 Status: {order['status']}\n"
            f"📅 Created: {order['created_at'][:16]}"
        )
        
        keyboard = [
            [InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_order_menu_{order_id}")],
            [InlineKeyboardButton("❌ Отменить заявку", callback_data=f"cancel_order_{order_id}")],
            [InlineKeyboardButton("⬅️ Назад в меню", callback_data="back_to_dispatcher_menu")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.edit_message_text(order_text, reply_markup=reply_markup)
        except Exception as e:
            if "not found" in str(e).lower():
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text=order_text,
                    reply_markup=reply_markup
                )
    
    elif data.startswith("change_status_"):
        # Handle status changes from master menu
        parts = data.split("_", 3)
        order_id = int(parts[2])
        new_status = parts[3]
        user_id = query.from_user.id
        
        # Get master info
        master_info = service_bot.get_user_info(user_id)
        master_name = master_info['full_name'] if master_info else f"Мастер {user_id}"
        
        # If changing to Completed status, start completion wizard
        if new_status == "Completed":
            context.user_data['completion_order_id'] = order_id
            
            try:
                await query.edit_message_text("💰 Введите сумму работ (в рублях):")
            except Exception as e:
                if "not found" in str(e).lower():
                    await context.bot.send_message(
                        chat_id=query.from_user.id,
                        text="💰 Введите сумму работ (в рублях):"
                    )
            
            return COMPLETION_AMOUNT
        
        # For other status changes, update normally
        service_bot.update_order(order_id, {'status': new_status})
        
        # Send confirmation to master
        try:
            await query.edit_message_text(f"✅ Заявка #{order_id} - статус изменён на {new_status}")
        except Exception as e:
            if "not found" in str(e).lower():
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text=f"✅ Заявка #{order_id} - статус изменён на {new_status}"
                )
        
        # Notify dispatcher about status change
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users WHERE role = 'dispatcher'")
            dispatchers = [row[0] for row in cursor.fetchall()]
            conn.close()
            
            for dispatcher_id in dispatchers:
                try:
                    await context.bot.send_message(
                        chat_id=dispatcher_id,
                        text=f"📊 Заявка #{order_id} - статус изменён на {new_status} мастером {master_name}"
                    )
                except Exception as e:
                    logger.error(f"Failed to notify dispatcher {dispatcher_id}: {e}")
        except Exception as e:
            logger.error(f"Error notifying dispatchers about order #{order_id} status change: {e}")
        
        logger.info(f"Order #{order_id} status changed to {new_status} by master {user_id}")
    
    elif data == "back_to_master_menu":
        # Return to master menu - regenerate the menu
        user_id = query.from_user.id
        
        # Get orders assigned to this master with relevant statuses
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, client_name, device_type, problem_short, status, created_at 
            FROM orders 
            WHERE master_id = ? AND status IN ('In Progress', 'Service', 'Modified')
            ORDER BY created_at DESC
        """, (user_id,))
        orders = cursor.fetchall()
        conn.close()
        
        if not orders:
            try:
                await query.edit_message_text("📋 У вас нет заявок со статусом 'В работе', 'В сервисе' или 'Изменено'.")
            except Exception as e:
                if "not found" in str(e).lower():
                    await context.bot.send_message(chat_id=query.from_user.id, text="📋 У вас нет заявок со статусом 'В работе', 'В сервисе' или 'Изменено'.")
            return
        
        # Create inline keyboard with order buttons
        keyboard = []
        for order in orders:
            order_id, client_name, device_type, problem_short, status, created_at = order
            button_text = f"#{order_id} - {status}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"master_order_{order_id}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = "🛠 Меню ваших заявок:\nВыберите заявку для просмотра деталей и управления статусом:"
        
        try:
            await query.edit_message_text(text, reply_markup=reply_markup)
        except Exception as e:
            if "not found" in str(e).lower():
                await context.bot.send_message(chat_id=query.from_user.id, text=text, reply_markup=reply_markup)
    
    elif data == "back_to_dispatcher_menu":
        # Return to dispatcher menu - regenerate the menu
        # Get all orders with relevant statuses
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, client_name, device_type, problem_short, status, created_at 
            FROM orders 
            WHERE status IN ('New', 'Guarantee', 'In Progress', 'Service', 'Modified')
            ORDER BY created_at DESC
        """)
        orders = cursor.fetchall()
        conn.close()
        
        if not orders:
            try:
                await query.edit_message_text("📋 No orders found with New, Guarantee, In Progress, Service, or Modified status.")
            except Exception as e:
                if "not found" in str(e).lower():
                    await context.bot.send_message(chat_id=query.from_user.id, text="📋 No orders found with New, Guarantee, In Progress, Service, or Modified status.")
            return
        
        # Create inline keyboard with order buttons and create request button
        keyboard = []
        
        # Add Create Request button at the top
        keyboard.append([InlineKeyboardButton("➕ Создать заявку", callback_data="create_request")])
        
        # Add separator
        if orders:
            keyboard.append([])  # Empty row for separation
        
        for order in orders:
            order_id, client_name, device_type, problem_short, status, created_at = order
            button_text = f"#{order_id} - {status}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"dispatcher_order_{order_id}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = "📋 Меню диспетчера:\nВыберите заявку для просмотра и управления или создайте новую:"
        
        try:
            await query.edit_message_text(text, reply_markup=reply_markup)
        except Exception as e:
            if "not found" in str(e).lower():
                await context.bot.send_message(chat_id=query.from_user.id, text=text, reply_markup=reply_markup)
    
    elif data.startswith("edit_order_menu_"):
        # Handle edit order from dispatcher menu
        order_id = int(data.split("_")[3])
        order = service_bot.get_order(order_id)
        
        if not order:
            try:
                await query.edit_message_text("❌ Order not found.")
            except Exception as e:
                if "not found" in str(e).lower():
                    await context.bot.send_message(chat_id=query.from_user.id, text="❌ Order not found.")
            return
        
        # Show edit menu
        order_text = (
            f"✏️ Edit Order #{order_id}:\n\n"
            f"📞 Phone: {order['client_phone']}\n"
            f"👤 Name: {order['client_name']}\n"
            f"📍 Address: {order['client_address']}\n"
            f"🔧 Device: {order['device_type']}\n"
            f"⚠️ Problem: {order['problem_short']}\n"
            f"📝 Full description: {order['problem_full'] or 'N/A'}\n"
            f"ℹ️ Additional info: {order['additional_info'] or 'N/A'}\n"
            f"📊 Status: {order['status']}"
        )
        
        keyboard = [
            [InlineKeyboardButton("📞 Изменить телефон", callback_data=f"edit_{order_id}_client_phone")],
            [InlineKeyboardButton("👤 Изменить имя", callback_data=f"edit_{order_id}_client_name")],
            [InlineKeyboardButton("📍 Изменить адрес", callback_data=f"edit_{order_id}_client_address")],
            [InlineKeyboardButton("🔧 Изменить устройство", callback_data=f"edit_{order_id}_device_type")],
            [InlineKeyboardButton("⚠️ Изменить проблему", callback_data=f"edit_{order_id}_problem_short")],
            [InlineKeyboardButton("📝 Изменить описание", callback_data=f"edit_{order_id}_problem_full")],
            [InlineKeyboardButton("ℹ️ Изменить доп. инфо", callback_data=f"edit_{order_id}_additional_info")],
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"dispatcher_order_{order_id}")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.edit_message_text(order_text, reply_markup=reply_markup)
        except Exception as e:
            if "not found" in str(e).lower():
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text=order_text,
                    reply_markup=reply_markup
                )
    
    elif data.startswith("cancel_order_"):
        # Handle order cancellation
        order_id = int(data.split("_")[2])
        
        # Get order info before cancellation to notify assigned master
        order = service_bot.get_order(order_id)
        
        # Update order status to Cancelled
        service_bot.update_order(order_id, {'status': 'Cancelled'})
        
        try:
            await query.edit_message_text(f"❌ Заявка #{order_id} отменена.")
        except Exception as e:
            if "not found" in str(e).lower():
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text=f"❌ Заявка #{order_id} отменена."
                )
        
        # Notify assigned master if there is one
        if order and order['master_id']:
            try:
                await context.bot.send_message(
                    chat_id=order['master_id'],
                    text=f"❌ Заявка #{order_id} была отменена диспетчером."
                )
                logger.info(f"Notified master {order['master_id']} about cancellation of order #{order_id}")
            except Exception as e:
                logger.error(f"Failed to notify master {order['master_id']} about order #{order_id} cancellation: {e}")
        
        # Delete notifications for all masters
        await service_bot.delete_notifications(order_id, context)
        
        logger.info(f"Order #{order_id} cancelled by dispatcher {query.from_user.id}")
    
    elif data == "create_request":
        # Handle create request from dispatcher menu
        # Send message to start new order conversation
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_new_order")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await query.edit_message_text(
                "📋 Creating new order...\n\n📞 Please enter client phone number (format: +7XXXXXXXXXX):\n\n💡 Use /cancel to stop at any time",
                reply_markup=reply_markup
            )
        except Exception as e:
            if "not found" in str(e).lower():
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text="📋 Creating new order...\n\n📞 Please enter client phone number (format: +7XXXXXXXXXX):\n\n💡 Use /cancel to stop at any time",
                    reply_markup=reply_markup
                )
        
        # Set conversation state
        return PHONE
    
    elif data.startswith("view_order_"):
        order_id = int(data.split("_")[2])
        order = service_bot.get_order(order_id)
        
        if not order:
            await query.edit_message_text("❌ Order not found.")
            return
        
        order_text = (
            f"📋 Order #{order_id} Details:\n\n"
            f"📞 Phone: {order['client_phone']}\n"
            f"👤 Name: {order['client_name']}\n"
            f"📍 Address: {order['client_address']}\n"
            f"🔧 Device: {order['device_type']}\n"
            f"⚠️ Problem: {order['problem_short']}\n"
            f"📝 Full description: {order['problem_full'] or 'N/A'}\n"
            f"ℹ️ Additional info: {order['additional_info'] or 'N/A'}\n"
            f"📊 Status: {order['status']}\n"
            f"📅 Created: {order['created_at'][:16]}"
        )
        
        keyboard = []
        # Accept button for New, Guarantee, and Modified orders
        if order['status'] in ['New', 'Guarantee', 'Modified']:
            keyboard.append([InlineKeyboardButton("✅ Принять заявку", callback_data=f"accept_{order_id}")])
        # Service/Complete buttons for assigned master's orders in progress
        elif order['status'] == 'In Progress' and order['master_id'] == query.from_user.id:
            keyboard.extend([
                [InlineKeyboardButton("➡️ В сервис", callback_data=f"to_service_{order_id}")],
                [InlineKeyboardButton("✅ Завершить", callback_data=f"complete_{order_id}")]
            ])
        # Service/Complete buttons for Service status orders
        elif order['status'] == 'Service' and order['master_id'] == query.from_user.id:
            keyboard.append([InlineKeyboardButton("✅ Завершить", callback_data=f"complete_{order_id}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        try:
            await query.edit_message_text(order_text, reply_markup=reply_markup)
        except Exception as e:
            if "not found" in str(e).lower() or "message to edit not found" in str(e).lower():
                # Message was deleted, send new message instead
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text=order_text,
                    reply_markup=reply_markup
                )
                logger.warning(f"Original message not found, sent new message for order #{order_id}")
            else:
                logger.error(f"Error editing message for order #{order_id}: {e}")
                raise
    
    elif data.startswith("accept_"):
        order_id = int(data.split("_")[1])
        user_id = query.from_user.id
        
        # Get master info
        master_info = service_bot.get_user_info(user_id)
        master_name = master_info['full_name'] if master_info else f"Master {user_id}"
        
        # Update order status and assign master
        service_bot.update_order(order_id, {
            'status': 'In Progress',
            'master_id': user_id
        })
        
        # Delete notifications from all masters
        await service_bot.delete_notifications(order_id, context)
        
        # Update current message
        keyboard = [
            [InlineKeyboardButton("➡️ В сервис", callback_data=f"to_service_{order_id}")],
            [InlineKeyboardButton("✅ Завершить", callback_data=f"complete_{order_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Send confirmation to master first
        try:
            await query.edit_message_text(
                f"✅ Вы приняли заявку #{order_id}. Статус: В работе",
                reply_markup=reply_markup
            )
        except Exception as e:
            if "not found" in str(e).lower() or "message to edit not found" in str(e).lower():
                # Message was deleted, send new message instead
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text=f"✅ Вы приняли заявку #{order_id}. Статус: В работе",
                    reply_markup=reply_markup
                )
                logger.warning(f"Original message not found, sent new message for order #{order_id} acceptance")
            else:
                logger.error(f"Error editing acceptance message for order #{order_id}: {e}")
                raise
        
        # Notify dispatcher about order acceptance
        try:
            # Get all dispatchers
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users WHERE role = 'dispatcher'")
            dispatchers = [row[0] for row in cursor.fetchall()]
            conn.close()
            
            # Send confirmation to dispatchers
            for dispatcher_id in dispatchers:
                try:
                    await context.bot.send_message(
                        chat_id=dispatcher_id,
                        text=f"👨‍🔧 {master_name} принял заявку #{order_id}"
                    )
                except Exception as e:
                    logger.error(f"Failed to notify dispatcher {dispatcher_id}: {e}")
                    
        except Exception as e:
            logger.error(f"Error notifying dispatchers about order #{order_id} acceptance: {e}")
        
        logger.info(f"Order #{order_id} accepted by master {user_id} ({master_name})")
    
    elif data.startswith("to_service_"):
        order_id = int(data.split("_")[2])
        user_id = query.from_user.id
        
        # Get master info
        master_info = service_bot.get_user_info(user_id)
        master_name = master_info['full_name'] if master_info else f"Master {user_id}"
        
        # Update order status
        service_bot.update_order(order_id, {'status': 'Service'})
        
        # Update master's message
        try:
            await query.edit_message_text(f"🔧 Status changed to Service")
        except Exception as e:
            if "not found" in str(e).lower() or "message to edit not found" in str(e).lower():
                # Message was deleted, send new message instead
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text=f"🔧 Status changed to Service"
                )
                logger.warning(f"Original message not found, sent new message for order #{order_id} service status")
            else:
                logger.error(f"Error editing service message for order #{order_id}: {e}")
                raise
        
        # Notify dispatcher
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users WHERE role = 'dispatcher'")
            dispatchers = [row[0] for row in cursor.fetchall()]
            conn.close()
            
            for dispatcher_id in dispatchers:
                try:
                    await context.bot.send_message(
                        chat_id=dispatcher_id,
                        text=f"🔧 Order #{order_id} moved to Service by {master_name}"
                    )
                except Exception as e:
                    logger.error(f"Failed to notify dispatcher {dispatcher_id}: {e}")
        except Exception as e:
            logger.error(f"Error notifying dispatchers about order #{order_id} service: {e}")
            
        logger.info(f"Order #{order_id} moved to Service by {master_name}")
    
    elif data.startswith("complete_"):
        order_id = int(data.split("_")[1])
        user_id = query.from_user.id
        
        # Start completion wizard
        context.user_data['completion_order_id'] = order_id
        
        try:
            await query.edit_message_text("💰 Введите полную сумму закрытия заявки (в рублях):")
        except Exception as e:
            if "not found" in str(e).lower() or "message to edit not found" in str(e).lower():
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text="💰 Введите полную сумму закрытия заявки (в рублях):"
                )
        
        return COMPLETION_AMOUNT
    
    elif data.startswith("edit_"):
        # Handle edit field selection
        parts = data.split("_", 2)
        order_id = int(parts[1])
        field = parts[2]
        
        # Store edit context
        context.user_data['edit_order_id'] = order_id
        context.user_data['edit_field'] = field
        
        # Field name mapping for user-friendly prompts
        field_names = {
            'client_phone': 'client phone number (+7XXXXXXXXXX)',
            'client_name': 'client name',
            'client_address': 'client address',
            'device_type': 'appliance type',
            'problem_short': 'short problem description',
            'problem_full': 'full problem description',
            'additional_info': 'additional information'
        }
        
        field_name = field_names.get(field, field)
        try:
            await query.edit_message_text(f"Please enter new {field_name}:")
        except Exception as e:
            if "not found" in str(e).lower() or "message to edit not found" in str(e).lower():
                # Message was deleted, send new message instead
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text=f"Please enter new {field_name}:"
                )
                logger.warning(f"Original message not found, sent new message for edit field {field}")
            else:
                logger.error(f"Error editing edit field message: {e}")
                raise
        
        logger.info(f"Starting edit of field '{field}' for order #{order_id}")
    
    elif data == "cancel_edit":
        try:
            await query.edit_message_text("❌ Edit operation cancelled.")
        except Exception as e:
            if "not found" in str(e).lower() or "message to edit not found" in str(e).lower():
                # Message was deleted, send new message instead
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text="❌ Edit operation cancelled."
                )
                logger.warning("Original message not found, sent new message for edit cancellation")
            else:
                logger.error(f"Error editing cancel message: {e}")
        context.user_data.clear()
        logger.info("Edit operation cancelled by user")
    
    elif data == "cancel_new_order":
        # Cancel order creation from inline button
        try:
            await query.edit_message_text("❌ Order creation cancelled")
        except Exception as e:
            if "not found" in str(e).lower() or "message to edit not found" in str(e).lower():
                # Message was deleted, send new message instead
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text="❌ Order creation cancelled"
                )
                logger.warning("Original message not found, sent new message for order cancellation")
            else:
                logger.error(f"Error editing cancel order message: {e}")
        context.user_data.clear()
        logger.info("Order creation cancelled via inline button")
        return ConversationHandler.END
    
    elif data == "skip_problem_full":
        # Skip problem full description
        try:
            await query.edit_message_text("Skipped full description. Moving to additional info...")
        except Exception as e:
            if "not found" in str(e).lower() or "message to edit not found" in str(e).lower():
                logger.warning("Original message not found for skip_problem_full")
            else:
                logger.error(f"Error editing skip problem message: {e}")
        keyboard = [
            [InlineKeyboardButton("⏭️ Пропустить", callback_data="skip_additional_info")],
            [InlineKeyboardButton("❌ Отменить", callback_data="cancel_new_order")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text="ℹ️ Пожалуйста, введите дополнительную информацию:\n\n💡 Используйте /skip или кнопку для завершения",
            reply_markup=reply_markup
        )
        return ADDITIONAL_INFO
    
    elif data == "skip_additional_info":
        # Skip additional info and create order
        try:
            await query.edit_message_text("Завершение создания заявки...")
        except Exception as e:
            if "not found" in str(e).lower() or "message to edit not found" in str(e).lower():
                logger.warning("Original message not found for skip_additional_info")
            else:
                logger.error(f"Error editing skip additional info message: {e}")
        return await complete_order_creation(query, context)
    
    elif data == "completion_document_yes":
        context.user_data['completion_document'] = "Да"
        
        keyboard = [
            [InlineKeyboardButton("⏭️ Пропустить", callback_data="completion_skip_additional")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await query.edit_message_text(
                "📝 Введите дополнительную информацию (или нажмите 'Пропустить'):",
                reply_markup=reply_markup
            )
        except Exception as e:
            if "not found" in str(e).lower():
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text="📝 Введите дополнительную информацию (или нажмите 'Пропустить'):",
                    reply_markup=reply_markup
                )
        
        return COMPLETION_ADDITIONAL
    
    elif data == "completion_document_no":
        context.user_data['completion_document'] = "Нет"
        
        keyboard = [
            [InlineKeyboardButton("⏭️ Пропустить", callback_data="completion_skip_additional")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await query.edit_message_text(
                "📝 Введите дополнительную информацию (или нажмите 'Пропустить'):",
                reply_markup=reply_markup
            )
        except Exception as e:
            if "not found" in str(e).lower():
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text="📝 Введите дополнительную информацию (или нажмите 'Пропустить'):",
                    reply_markup=reply_markup
                )
        
        return COMPLETION_ADDITIONAL
    
    elif data == "completion_skip_additional":
        context.user_data['completion_additional'] = ""
        return await finalize_completion_callback(query, context)
    
    elif data.startswith("view_completed_"):
        # Handle viewing completed order details
        order_id = int(data.split("_")[2])
        
        # Get order details
        order = service_bot.get_order(order_id)
        if not order:
            try:
                await query.edit_message_text("❌ Заявка не найдена.")
            except Exception as e:
                if "not found" in str(e).lower():
                    await context.bot.send_message(
                        chat_id=query.from_user.id,
                        text="❌ Заявка не найдена."
                    )
            return
        
        # Format completed order details
        order_text = f"✅ Завершённая заявка #{order['id']}\n\n"
        order_text += f"👤 Клиент: {order['client_name']}\n"
        order_text += f"📞 Телефон: {order['client_phone']}\n"
        order_text += f"📍 Адрес: {order['client_address']}\n"
        order_text += f"🔧 Устройство: {order['device_type']}\n"
        order_text += f"⚠️ Проблема: {order['problem_short']}\n"
        
        if order['problem_full']:
            order_text += f"📝 Подробное описание: {order['problem_full']}\n"
        
        if order['additional_info']:
            order_text += f"ℹ️ Доп. информация: {order['additional_info']}\n"
        
        order_text += f"📅 Создана: {order['created_at']}\n"
        
        if order['completion_amount']:
            order_text += f"💰 Сумма работ: {order['completion_amount']} руб.\n"
        
        if order['completion_document']:
            order_text += f"📄 Документ оставлен: {order['completion_document']}\n"
            
        if order['completion_additional']:
            order_text += f"📝 Доп. информация по завершению: {order['completion_additional']}\n"
        
        # Back button
        keyboard = [
            [InlineKeyboardButton("🔙 Назад к списку", callback_data="back_to_closed_orders")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await query.edit_message_text(order_text, reply_markup=reply_markup)
        except Exception as e:
            if "not found" in str(e).lower():
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text=order_text,
                    reply_markup=reply_markup
                )
    
    elif data == "back_to_closed_orders":
        # Return to closed orders list
        user_id = query.from_user.id
        
        # Get completed orders for this master
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, client_name, client_phone, device_type, problem_short, created_at, 
                   completion_amount, completion_document, completion_additional
            FROM orders 
            WHERE master_id = ? AND status = 'Completed'
            ORDER BY created_at DESC
            LIMIT 20
        """, (user_id,))
        orders = cursor.fetchall()
        conn.close()
        
        if not orders:
            try:
                await query.edit_message_text("📋 У вас нет завершённых заявок.")
            except Exception as e:
                if "not found" in str(e).lower():
                    await context.bot.send_message(chat_id=query.from_user.id, text="📋 У вас нет завершённых заявок.")
            return
        
        # Create navigation buttons
        keyboard = []
        for order in orders:
            order_id, client_name, client_phone, device_type, problem_short, created_at, amount, document, additional = order
            button_text = f"#{order_id} | {client_phone}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"view_completed_{order_id}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await query.edit_message_text(
                "📋 Ваши завершённые заявки:\n\nВыберите заявку для просмотра деталей:",
                reply_markup=reply_markup
            )
        except Exception as e:
            if "not found" in str(e).lower():
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text="📋 Ваши завершённые заявки:\n\nВыберите заявку для просмотра деталей:",
                    reply_markup=reply_markup
                )
    
    elif data == "ignore":
        try:
            await query.edit_message_text("Уведомление отклонено.")
        except Exception as e:
            if "not found" in str(e).lower() or "message to edit not found" in str(e).lower():
                # Message was already deleted, no need to dismiss
                logger.warning("Original notification message not found for dismiss")
            else:
                logger.error(f"Error editing dismiss message: {e}")

def main():
    """Main function to run the bot"""
    # Get bot token from environment variable
    bot_token = '8458834609:AAHW44NjF-TauZ8s32XtJqkoFpYHPKFd3nI'
    
    if not bot_token:
        print("❌ Error: BOT_TOKEN environment variable not set!")
        print("Please provide your Telegram bot token:")
        print("1. Get token from @BotFather on Telegram")
        print("2. Set environment variable: export BOT_TOKEN='your_token_here'")
        print("3. Or add it to your .env file")
        exit(1)
    
    # Create application
    application = Application.builder().token(bot_token).build()
    
    # Create conversation handler for new order
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("new_order", new_order),
            CallbackQueryHandler(handle_callback_query, pattern="^create_request$")
        ],
        states={
            PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone),
                CallbackQueryHandler(handle_callback_query, pattern="^cancel_new_order$")
            ],
            CLIENT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_client_name),
                CallbackQueryHandler(handle_callback_query, pattern="^cancel_new_order$")
            ],
            ADDRESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_address),
                CallbackQueryHandler(handle_callback_query, pattern="^cancel_new_order$")
            ],
            DEVICE_TYPE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_device_type),
                CallbackQueryHandler(handle_callback_query, pattern="^cancel_new_order$")
            ],
            PROBLEM_SHORT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_problem_short),
                CallbackQueryHandler(handle_callback_query, pattern="^cancel_new_order$")
            ],
            PROBLEM_FULL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_problem_full),
                CommandHandler("skip", skip_field),
                CallbackQueryHandler(handle_callback_query, pattern="^(skip_problem_full|cancel_new_order)$")
            ],
            ADDITIONAL_INFO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_additional_info),
                CommandHandler("skip", skip_field),
                CallbackQueryHandler(handle_callback_query, pattern="^(skip_additional_info|cancel_new_order)$")
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_order_creation),
            CallbackQueryHandler(handle_callback_query, pattern="^cancel_new_order$")
        ]
    )
    
    # Create completion conversation handler
    completion_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_callback_query, pattern="^complete_")],
        states={
            COMPLETION_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_completion_amount)
            ],
            COMPLETION_DOCUMENT: [
                CallbackQueryHandler(handle_callback_query, pattern="^completion_document_")
            ],
            COMPLETION_ADDITIONAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_completion_additional),
                CallbackQueryHandler(handle_callback_query, pattern="^completion_skip_additional$")
            ]
        },
        fallbacks=[
            CommandHandler("cancel", lambda u, c: ConversationHandler.END)
        ]
    )

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(conv_handler)
    application.add_handler(completion_handler)
    application.add_handler(CommandHandler("edit_order", edit_order))
    application.add_handler(CommandHandler("my_orders", my_orders))
    application.add_handler(CommandHandler("closed_orders", closed_orders))
    application.add_handler(CommandHandler("all_orders", all_orders))
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    
    # Add message handler for edit field values (with lower priority)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, 
        handle_edit_field_value
    ), group=1)
    
    # Initialize database and add sample users if needed
    service_bot.init_database()
    
    print("🤖 Telegram Bot for Home Appliance Service Center")
    print("✅ Bot is starting...")
    print("📋 Database initialized")
    print("🔑 Add users to the database using the database.sql file")
    print("⚡ Bot is ready to receive messages!")
    
    # Run the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()