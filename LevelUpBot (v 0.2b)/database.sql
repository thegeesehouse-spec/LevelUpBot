-- Home Appliance Service Center Database Schema
-- This file contains sample data for testing the bot

-- Insert sample users (dispatchers and masters)
INSERT OR IGNORE INTO users (user_id, role, full_name) VALUES
(123456789, 'dispatcher', 'John Dispatcher'),
(987654321, 'master', 'Mike Master'),
(555666777, 'master', 'Sarah Technician');

-- Note: Replace the user_id values above with actual Telegram user IDs
-- To get your Telegram user ID, you can:
-- 1. Message @userinfobot on Telegram
-- 2. Use the /start command and check the logs for your user ID
-- 3. Use @RawDataBot to get your user information

-- The bot will automatically create the tables when it starts
-- You only need to insert your actual user data into the users table
