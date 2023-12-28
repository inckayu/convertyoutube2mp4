import logging
import urllib.parse
from slack_bolt import (App, Ack)
from slack_sdk import WebClient
from slack_bolt.adapter.aws_lambda import SlackRequestHandler
import yt_dlp
import boto3
import glob
import os
import re
import utils.constants as constants
from utils.slack import (
    post_message,
    post_dm
)

app = App(token=constants.SLACK_TOKEN, signing_secret=constants.SLACK_SIGNING_SECRET, process_before_response=True,)

logger = logging.getLogger()
# logger.setLevel(logging.DEBUG)
logger.setLevel(logging.INFO)

def extract_youtube_url(text):
    pattern = r"https://www\.youtube\.com/watch\?v=[\w-]+"
    matches = re.findall(pattern, text)
    return matches[0]

# Function to upload files to S3
def upload_to_s3(file_name, bucket_name, s3_file_name=None):
    logger.info(f"upload to mp3 {file_name}")
    if s3_file_name is None:
        s3_file_name = file_name

    try:
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=constants.AWS_NORMAL_ACCESS_KEY_ID,
            aws_secret_access_key=constants.AWS_SECRET_ACCESS_KEY_ID,
        )
        print(file_name)
        s3_client.upload_file(file_name, bucket_name, s3_file_name.replace("/tmp/", ""))
        print("k")
        logger.info(f"File {file_name} uploaded to {bucket_name}/{s3_file_name}")
    except Exception as e:
        logger.info(f"Error: {e}")
        print(e)

def convert_to_mp3(urls, fmt):
    logger.info(f"convert to mp3: {urls}")
    output_urls = []
    output_names = []
    ydl_opts = {
        # 'format': 'mp4',
        'outtmpl': '/tmp/%(title)s.%(ext)s',
        'format': 'mp3/bestaudio/best',
        'postprocessors': [{  # Extract audio using ffmpeg
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
        }],
        'ffmpeg-location': 'opt/bin/ffmpeg',
    } if fmt == "mp3" else {
        'format': 'mp4',
        'outtmpl': '/tmp/%(title)s.%(ext)s',
    }
    # Download and upload process
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        # error_code = ydl.download(URLS)
        for url in urls:
            info_dict = ydl.extract_info(extract_youtube_url(url))
            file_name = ydl.prepare_filename(info_dict).replace(".mkv", ".mp4")
            print(file_name)
            output_urls.append(
                constants.AWS_S3_URL
                + urllib.parse.quote(file_name, safe=":/").replace("/tmp/", "")
            )
            output_names.append(file_name.replace(".mp4", "").replace("/tmp/", ""))
            upload_to_s3(file_name, constants.AWS_S3_BUCKET_NAME)
        print(output_urls)
        for p in glob.glob('/tmp/' + '*'):
            if os.path.isfile(p):
                os.remove(p)
        return output_urls, output_names

def just_ack(ack: Ack):
    ack()

def start_modal_interaction(body: dict, client: WebClient):
    # 入力項目ひとつだけのシンプルなモーダルを開く
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "submit",
            "submit": {"type": "plain_text", "text": "変換", "emoji": True},
            "close": {"type": "plain_text", "text": "キャンセル", "emoji": True},
            "title": {"type": "plain_text", "text": "YouTubeの動画をmp4に変換する", "emoji": True},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "plain_text",
                        "text": "今はmp4にしか変換できないモル:tired_face:",
                        # "text": "変換したいYouTubeのURLを入力するモル:bangbang:\n複数のURLを入力したい場合は間にカンマ(,)を入れるモル:bangbang:カンマは半角モル。カンマの前後にスペースを入れちゃダメモル:tired_face:\n動画のURLをたくさん入力すると容量が大きすぎて変換できないことがあるモルから、入力したURLの動画の合計再生時間が最大でも30分くらいになるようにしてほしいモル:bangbang:",
                        "emoji": True,
                    },
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*フォーマット*"
                    },
                    "accessory": {
                        "type": "radio_buttons",
                        "options": [
                            {
                                "text": {
                                    "type": "plain_text",
                                    "text": "mp3",
                                    "emoji": True
                                },
                                "value": "mp3"
                            },
                            {
                                "text": {
                                    "type": "plain_text",
                                    "text": "mp4",
                                    "emoji": True
                                },
                                "value": "mp4"
                            },
                        ],
                        "action_id": "radio_buttons-action"
                    }
                },
                {"type": "divider"},
                {
                    "type": "input",
                    "label": {"type": "plain_text", "text": "URL", "emoji": True},
                    "element": {"type": "plain_text_input", "multiline": True},
                },
            ],
        }
    )

def handle_modal(ack: Ack):
    # ack() は何も渡さず呼ぶとただ今のモーダルを閉じるだけ
    # response_action とともに応答すると
    # エラーを表示したり、モーダルの内容を更新したりできる
    ack(
        response_action="update",
        view={
            "type": "modal",
            "callback_id": "modal-id",
            "title": {"type": "plain_text", "text": "YouTubeの動画をmp4に変換する"},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "plain_text",
                        "text": "変換中モル:bangbang:動画の時間が長いと最大5分くらいかかるかもしれないモルけど、画面を閉じちゃダメモル:tired_face:",
                    },
                }
            ],
        },
    )

# モーダルで送信ボタンが押されたときに非同期で実行される処理
# モーダルの操作以外で時間のかかる処理があればこちらに書く
def handle_time_consuming_task(view: dict, client: WebClient, logger: logging.Logger):
    logger.setLevel(logging.INFO)
    urls = list(list(view["state"]["values"].values())[1].values())[0][
        "value"
    ].split(",")
    fmt = list(
            view["state"]["values"].values()
        )[0]["radio_buttons-action"]["selected_option"]["value"]
    logger.info(f"FORMAT: {fmt}")
    
    # user = slack_event["user"]["id"]
    urls = [url.replace(" ", "") for url in urls]
    links = []
    try:
        results, names = convert_to_mp3(urls, fmt)
    except Exception as e:
        client.views_update(
            view_id=view.get("id"),
            view={
                "type": "modal",
                "callback_id": "convert2mp3",
                "title": {"type": "plain_text", "text": "YouTubeの動画をmp4に変換する"},
                "close": {"type": "plain_text", "text": "閉じる"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"変換中にエラーが発生したモル:tired_face:もう一度やり直してほしいモル。\n\n{e}"},
                    }
                ],
            },
        )
        return

    for index, name in enumerate(names):
        links.append(f"<{results[index]}|{name}>")
    logger.info(urls)
    logger.info(links)
    logger.info(names)
    post_message("YouTubeの動画がmp4に変換されたモル:star-struck:\n\n・" + "\n・".join(links))

    client.views_update(
        view_id=view.get("id"),
        view={
            "type": "modal",
            "callback_id": "convert2mp3",
            "title": {"type": "plain_text", "text": "YouTubeの動画をmp4に変換する"},
            "close": {"type": "plain_text", "text": "閉じる"},
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "YouTubeの動画をmp4に変換できたモル:star-struck:下記のURLからダウンロードするモル:bangbang:\n\n・" + '\n・'.join(links)},
                }
            ],
        },
    )

def handle_radio_buttons(logger: logging.Logger, view: dict, client: WebClient):
    logger.info(f"radio buttons event: {view}")
    logger.info(f"radio buttons event: {client}")

# convert2mp3というcallback idに対応する処理を登録
app.shortcut("convert2mp3")(
    ack=just_ack,
    lazy=[start_modal_interaction],
)

# 送信ボタンが押されたときの処理を登録
app.view("submit")(
    ack=handle_modal,
    lazy=[handle_time_consuming_task],
)

app.action("radio_buttons-action")(
    ack=just_ack,
    lazy=[handle_radio_buttons],
)

slack_handler = SlackRequestHandler(app)

def lambda_handler(event, context):
    return slack_handler.handle(event, context)

# convert_to_mp3(URLS)
