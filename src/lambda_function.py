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

def convert_to_mp3(urls):
    logger.info(f"convert to mp3: {urls}")
    output_urls = []
    output_names = []
    ydl_opts = {
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
                            "text": "変換したいYouTubeのURLを入力するモル:bangbang:\n複数のURLを入力したい場合は間にカンマ(,)を入れるモル:bangbang:カンマは半角モル。カンマの前後にスペースを入れちゃダメモル:tired_face:\n動画のURLをたくさん入力すると容量が大きすぎて変換できないことがあるモルから、入力したURLの動画の合計再生時間が最大でも30分くらいになるようにしてほしいモル:bangbang:",
                            "emoji": True,
                        },
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
def handle_time_consuming_task(logger: logging.Logger, view: dict, client: WebClient):
    logger.info(view)
    urls = list(list(view["state"]["values"].values())[0].values())[0][
        "value"
    ].split(",")
    # user = slack_event["user"]["id"]
    urls = [url.replace(" ", "") for url in urls]
    links = []
    results, names = convert_to_mp3(urls)
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

slack_handler = SlackRequestHandler(app)

def lambda_handler(event, context):
    return slack_handler.handle(event, context)

# convert_to_mp3(URLS)
