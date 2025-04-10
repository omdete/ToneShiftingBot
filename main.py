from getpass import getpass

import requests
from telegram import Update
from telegram.ext import CommandHandler, MessageHandler, CallbackContext, ApplicationBuilder, ContextTypes
import telegram.ext.filters as filters

import subprocess
import os

import librosa
import librosa.display
import soundfile as sf
from pathlib import Path
import yt_dlp


def main():
    """ Core function of the Telegram bot.

    This bot's main purpose is to receive a YT URL, download its audio, and optionally adjust its pitch.
    The final audio is then sent back to the user.

    """
    token = load_password()
    query = requests.get(f"https://api.telegram.org/bot{token}/getMe")
    assert query.status_code == 200, "Querying Telegram Bot API failed."
    if query.json().get("ok"):
        print("Telegram bot is already running!")
        return

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download_url))
    print("Ready \u2705")
    app.run_polling()


def load_password(private_key_path: str = "~/.ssh/id_rsa",
                  token_path: str = "./token.enc") -> str:
    """ Loads the Telegram bot's login token.

    Args:
        private_key_path (str):
            SSH private key to be used to decode the login token.

        token_path (str):
            Path to the encrypted login token. This token was encrypted with the SSH public key such that:

            ```bash
                echo "TELEGRAM_LOGIN_TOKEN" | age -R ~/.ssh/id_rsa.pub > token.enc
            ```

    Returns:
         Plain text of the Telegram bot's login token.
    """
    private_key_path = os.path.expanduser(private_key_path)

    if not os.path.exists(token_path) or not os.path.exists(private_key_path):
        return os.getenv("TOKEN") or getpass("Please enter the login token: ")

    try:
        result = subprocess.run(
            ["age", "-d", "-i", private_key_path, token_path],
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip()  # Remove extra newlines

    except subprocess.CalledProcessError as e:
        raise NotImplementedError(str(e))



async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ Simple introductory text for the bot.

    It will be activated at the beginning of the conversation and everytime the user sends /start message.
    """
    await update.message.reply_text("Send me a URL, and I'll download the audio for you!")
    await help(update, context)


async def help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ Help message for the bot.

    It will be activated when the user sends /help message.
    """
    await update.message.reply_text("Your messages should have the following format:\n\n"
                                    "https://url.to.a.yt.video semitones(optional)\n\n"
                                    "For instance:\n\n"
                                    "'https://url.to.a.yt.video 1' will send you the video's audio shifted 1 semitone up.\n\n"
                                    "'https://url.to.a.yt.video -2' will send you the video's audio shifted 2 semitone down.\n\n"
                                    "'https://url.to.a.yt.video' will send you the video's original audio.\n\n")


async def download_url(update: Update, context: CallbackContext) -> None:
    """ Downloads the URL's audio, shifts it tonality, and sends the user the processed video.

    It will be activated each time a user sends a message that is not a command. (Commands start with "/").
    """
    parts = update.message.text.split()
    if len(parts) > 2:
        await update.message.reply_text(f"Invalid text format. It must be a URL only or a URL plus a number indicating the tone shift.")

    try:
        url = parts[0]
        semitones = int(parts[1]) if len(parts) == 2 else 0

        audio_path = download_audio(url)
        await update.message.reply_text(f"Downloaded content: {audio_path.name}")
        processed_file = lower_pitch(audio_path, semitones=semitones)

        # Send the audio file
        with open(processed_file, "rb") as audio:
            await update.message.reply_audio(audio)
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")


def download_audio(yt_url, output_path: str = "downloads") -> Path:
    """ Downloads the audio of a yt URL.

    Args:
        yt_url (str):
            YT video URL.

        output_path:
            Local path to store the downloaded audio.

    Returns:
         Local path to the downloaded audio file.
    """
    ydl_opts = {
        'format': 'bestaudio/best',  # Best available audio format
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',  # Extract audio
            'preferredcodec': 'mp3',  # Convert to MP3 (change to 'm4a' or 'opus' if needed)
            'preferredquality': '192',  # Audio quality
        }],
        'outtmpl': f'{output_path}/%(title)s',  # Save as title.mp3
        'quiet': True,  # Suppress output
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(yt_url, download=False)
        filename = ydl.prepare_filename(info)  # Get filename before post-processing

        # Convert filename to MP3 format if changed by FFmpeg
        filename = filename.rsplit('.', 1)[0] + ".mp3"
        if os.path.exists(filename):
            return Path(filename)

        ydl.extract_info(yt_url, download=True)
        return Path(filename)  # Return stored file name


def lower_pitch(audio_file: Path, semitones: int = -2) -> str:
    """ Shifts the pitch of the audio.

    Args:
        audio_file: (str)
            Local path to the audio file.

        semitones (int):
            Amount of semitones to shift the audio's pitch. If bigger than zero, it will be shifted higher.
            If lower than zero, it will be shifted lower.

    Returns:
         Path to the shifted tone's audio file.
    """
    if semitones == 0:
        return str(audio_file)

    output_file = os.path.join(audio_file.parent.name, f"(ST {'+' if semitones > 0 else '-'}{abs(semitones)}) {audio_file.name}")
    if os.path.exists(output_file):
        return output_file

    # Load audio file
    y, sr = librosa.load(str(audio_file), sr=None)  # Keep original sample rate

    # Lower the pitch
    y_shifted = librosa.effects.pitch_shift(y, sr=sr, n_steps=semitones)

    # Save modified audio
    sf.write(output_file, y_shifted, sr)
    return output_file


if __name__ == "__main__":
    main()


