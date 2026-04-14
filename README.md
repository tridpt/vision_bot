# 👁️ Vision AI Bot - Smart Camera Monitoring Assistant

![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)
![Gemini AI](https://img.shields.io/badge/AI-Google_Gemini-orange.svg)
![OpenCV](https://img.shields.io/badge/cvision-OpenCV-green.svg)

An intelligent local AI agent that turns your computer's webcam into a "Surveillance Machine" integrated with Telegram for scene analysis and automatic motion-triggered alerts.

## 🚀 Features

- 🧠 **Vision AI:** Capable of observing and accurately analyzing the environment using the [Google Gemini 2.5](https://aistudio.google.com/) multimodal model.
- 🚨 **Motion Alert Radar:** Detects any physical movement (humans/animals) in the frame using the frame differencing algorithm (OpenCV `absdiff`).
- 💬 **Telegram Control:** Seamless integration with Telegram, allowing 24/7 on-demand capturing and monitoring right from your phone.
- 🥷 **Ghost Daemon Mode:** Runs completely silently in the background on Windows using `pythonw` with ZERO terminal windows. 
- 🛡️ **Absolute Security:** Environment variables (`.env`) for secrets and hardcore identity verification (Telegram User ID to reject any unauthorized snoopers from accessing the camera).

## 🛠️ Installation Guide

### 1. Requirements Prep
Clone this repository and install the dependencies:
```bash
pip install -r requirements.txt
```

### 2. Environment Setup
CRITICAL: To enable secure connections, you must provide your API keys.
* Rename `.env.example` to `.env`
* Obtain your Telegram Bot Token via **@BotFather** on Telegram.
* Get your free Gemini API key from **Google AI Studio**.
* Get your Personal Telegram ID via **@userinfobot**.
* Open `.env` and fill in the values (never upload this file publicly):

```env
TELEGRAM_BOT_TOKEN="Your_telegram_Token..."
GEMINI_API_KEY="Your_API_KEY..."
ALLOWED_USER_ID="Your_ID"
```

## 🎮 Usage & Controls

You don't need to touch the terminal to run this!

1. Double-click `Chay_Bot_Ngam.vbs` to launch the logic into background mode. (Pro-tip: Throw this file into your Windows `Startup` folder so the bot wakes up alongside your PC).
2. If you want some privacy or need to shut it down, simply run `Tat_Bot.bat` to eliminate the silent background process.

### 🤖 Telegram Bot Commands
| Command / Action | Functionality |
| :--- | :--- |
| *Standard Text Message* | Immediately captures a snapshot of the current environment, then passes both the photo and your text message to the AI for analysis. |
| `/auto` | **TURN ON Motion Radar**. Detects shifts within the camera frame. If an intrusion is detected, it snaps a photo and blasts an alert to your phone. Includes a 10s cooldown to prevent notification spam. |
| `/stop` | **TURN OFF Radar**. Releases the camera hardware and pauses monitoring, ensuring user privacy and saving power. |

---
*Developed with a passion for Automated OS Integrations and AI Agents.*
