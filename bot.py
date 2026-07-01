import os
import json
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from config import Config
import openai

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=Config.LOG_LEVEL
)
logger = logging.getLogger(__name__)

# Initialize OpenAI
openai.api_key = Config.OPENAI_API_KEY

# Load database schemas
with open('database_schemas.json', 'r') as f:
    SCHEMAS = json.load(f)

# Store user sessions
user_sessions = {}

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message when /start is issued."""
    user = update.effective_user
    
    # Create schema selection keyboard
    keyboard = []
    for schema_name, schema_data in SCHEMAS['schemas'].items():
        keyboard.append([InlineKeyboardButton(
            schema_data['name'], 
            callback_data=f"schema_{schema_name}"
        )])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👋 Hello {user.first_name}!\n\n"
        f"I'm an SQL Query Generator Bot. I can help you generate SQL queries from natural language.\n\n"
        f"📊 Select a database schema to get started:",
        reply_markup=reply_markup
    )

async def schema_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle schema selection."""
    query = update.callback_query
    await query.answer()
    
    schema_key = query.data.replace('schema_', '')
    selected_schema = SCHEMAS['schemas'][schema_key]
    
    # Store selected schema in user session
    user_id = query.from_user.id
    if user_id not in user_sessions:
        user_sessions[user_id] = {}
    user_sessions[user_id]['schema'] = selected_schema
    user_sessions[user_id]['schema_key'] = schema_key
    
    # Display schema details
    schema_info = f"📊 **{selected_schema['name']}**\n\n"
    schema_info += f"{selected_schema['description']}\n\n"
    schema_info += "**Tables available:**\n"
    
    for table_name, table_data in selected_schema['tables'].items():
        schema_info += f"\n📋 **{table_name}**\n"
        for column in table_data['columns']:
            schema_info += f"  • {column['name']} ({column['type']}) - {column['description']}\n"
    
    await query.edit_message_text(
        schema_info,
        parse_mode='Markdown'
    )
    
    # Ask for the natural language query
    await query.message.reply_text(
        f"✅ Schema selected: **{selected_schema['name']}**\n\n"
        f"Now, describe what you want to query in natural language.\n"
        f"Example: *'Get all customers who placed orders in the last 30 days'*\n\n"
        f"Type your query:",
        parse_mode='Markdown'
    )

async def generate_sql(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate SQL from natural language."""
    user_id = update.effective_user.id
    natural_query = update.message.text
    
    # Check if user has selected a schema
    if user_id not in user_sessions or 'schema' not in user_sessions[user_id]:
        await update.message.reply_text(
            "⚠️ Please select a database schema first using /start"
        )
        return
    
    selected_schema = user_sessions[user_id]['schema']
    
    # Show typing indicator
    await update.message.chat.send_action(action="typing")
    
    try:
        # Prepare the prompt for OpenAI
        prompt = create_prompt(natural_query, selected_schema)
        
        # Call OpenAI API
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an expert SQL query generator. Generate SQL queries based on natural language descriptions and the provided database schema. Only return the SQL query, nothing else."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        
        sql_query = response.choices[0].message.content.strip()
        
        # Store the generated SQL in session for reference
        user_sessions[user_id]['last_query'] = natural_query
        user_sessions[user_id]['last_sql'] = sql_query
        
        # Send the SQL query with formatting
        await update.message.reply_text(
            f"🔍 **Natural Language Query:**\n{natural_query}\n\n"
            f"📝 **Generated SQL:**\n```sql\n{sql_query}\n```\n\n"
            f"💡 **Tips:**\n"
            f"• Check the query for your specific database\n"
            f"• Use /reset to choose a different schema\n"
            f"• Use /help for more commands",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error generating SQL: {str(e)}")
        await update.message.reply_text(
            f"❌ Error generating SQL: {str(e)}\n\n"
            f"Please try rephrasing your query or check the schema."
        )

def create_prompt(natural_query, schema):
    """Create a prompt for the AI."""
    schema_description = f"Database Schema: {schema['name']}\n\n"
    
    for table_name, table_data in schema['tables'].items():
        schema_description += f"Table: {table_name}\n"
        columns = [f"{col['name']} ({col['type']})" for col in table_data['columns']]
        schema_description += f"Columns: {', '.join(columns)}\n\n"
    
    prompt = f"""
Given this database schema:

{schema_description}

Generate a SQL query for this request: "{natural_query}"

Requirements:
1. Use proper SQL syntax
2. Include appropriate JOINs if needed
3. Use meaningful table aliases
4. Include proper WHERE conditions
5. Return only the SQL query, no explanations

SQL Query:
"""
    return prompt

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset user session and allow schema reselection."""
    user_id = update.effective_user.id
    
    # Clear session
    if user_id in user_sessions:
        del user_sessions[user_id]
    
    await update.message.reply_text(
        "🔄 Session reset! Please use /start to select a new database schema."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send help message."""
    help_text = """
🤖 **SQL Query Generator Bot Commands**

/start - Start the bot and select a database schema
/help - Show this help message
/reset - Reset your session and choose a new schema
/about - About this bot

**How to use:**
1. Start with /start and choose a database schema
2. Type your query in natural language
3. The bot will generate the SQL query for you

**Example natural language queries:**
• "Show all customers who ordered more than 5 items"
• "Get the total sales per month for 2024"
• "Find authors who published books in the last 5 years"
• "List members who haven't returned books"

**Supported Schemas:**
• E-Commerce Database (customers, orders, products, order_items)
• Library Database (authors, books, members, borrowings)
"""
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send about information."""
    about_text = """
📊 **SQL Query Generator Bot v1.0**

This bot uses OpenAI's GPT to convert natural language queries into SQL.

**Features:**
• Multiple database schemas support
• Natural language to SQL conversion
• Query history (use /history)
• Context-aware generation

**Tech Stack:**
• Python + python-telegram-bot
• OpenAI GPT-3.5-turbo
• Deployed on Railway

**Developer:** @YourUsername
**Source Code:** github.com/YourUsername/SQLQueryGeneratorBot
"""
    
    await update.message.reply_text(about_text, parse_mode='Markdown')

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show query history for the current session."""
    user_id = update.effective_user.id
    
    if user_id not in user_sessions or 'last_query' not in user_sessions[user_id]:
        await update.message.reply_text(
            "📋 No query history found. Generate a SQL query first!"
        )
        return
    
    session = user_sessions[user_id]
    
    history_text = (
        f"📋 **Query History**\n\n"
        f"**Last Query:**\n{session['last_query']}\n\n"
        f"**Generated SQL:**\n```sql\n{session['last_sql']}\n```"
    )
    
    await update.message.reply_text(history_text, parse_mode='Markdown')

def main():
    """Start the bot."""
    logger.info("Starting SQL Query Generator Bot...")
    
    # Create the Application
    application = ApplicationBuilder().token(Config.BOT_TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CommandHandler("history", history_command))
    
    # Add callback query handler for schema selection
    application.add_handler(CallbackQueryHandler(schema_selection, pattern="schema_"))
    
    # Add message handler for natural language queries
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, generate_sql))

    # Start the bot
    logger.info("Bot is running and polling for updates...")
    application.run_polling()

if __name__ == '__main__':
    main()
