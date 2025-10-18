#!/bin/bash

# Start the web app in the background
python app.py &

# Start the Discord bot
python discord_bot.py
