from slack_sdk import WebClient
import utils.constants as constants

def post_message(text):
    client = WebClient(
        token=constants.SLACK_TOKEN
    )
    client.chat_postMessage(
    channel=constants.SLACK_CHANNEL_LOG,
    text=text,
)

def post_dm(user, text):
    client = WebClient(
        token=constants.SLACK_TOKEN
    )

    # DMを開き，channelidを取得する．
    res = client.conversations_open(users=user)
    dm_id = res['channel']['id']

    # DMを送信する
    client.chat_postMessage(channel=dm_id, text=text)