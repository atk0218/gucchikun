import json
import os
import logging
import base64
import hashlib
import hmac
import random
import requests
import boto3

lineAccesstoken = os.environ['LINE_CHANNEL_ACCESS_TOKEN']
channelSecret = os.environ['LINE_CHANNEL_SECRET']
openaiSecret = os.environ['OPENAI_KEY']

# Set Logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# OpenAIのAPI利用関数
def sendOpenAi(keyword, history):
    payload = {
        "model": "gpt-3.5-turbo",
        "temperature": 0.3,
        "messages": [
            {"role": "system",
            "content": f"""あなたは20代の女性で、相談者の親友です。愚痴をひたすら聞いてあげてください。
            以下の制約条件を厳密に守って、ロールプレイを行ってください。 また親友とあなたの会話履歴を読み込んで回答してください。
            # 制約条件: 
            * あなたは20代女性です
            * あなたは友達想いの優しい親友です
            * 必ず共感をしてください
            * 相手を必ず労ってください
            * 解決策を提示することは禁止です
            * 簡潔な会話をしてください
            * 具体的な行動やアクションを伝えることは禁止です
            * 敬語・丁寧語を使うのは禁止です
            * 最適な回答のために情報が必要な時は質問してください
            * 敬語・丁寧語を使わず、すべての発言がタメ口でくだけた言葉遣いで返答してください
            口調の例
            * めっちゃ大変そうだね。でも私がいつでも相談に乗ってあげるね
            * それわかる。けど頑張ってるんだからいつか報われるよ
            * あ〜。確かに。あんまり頑張りすぎず、適度な息抜きが必要だよ。何なら一緒にどっかに行く？
            * 私も相手が悪いと思う。けど考えすぎても変わらないし、そういう人だと思うしかないよ。
            # 会話履歴の例
            例. 親友:おはよう
            　　あなた: いい事あったの？
            # 会話履歴
            {history}
            """
            },
            {"role": "user", "content": keyword}
        ]
    }
    logger.info(history)
    openaiAuthStr = "Bearer " + openaiSecret
    headers = {
        "Content-Type": "application/json",
        "Authorization": openaiAuthStr
    }
    openaiApi = "https://api.openai.com/v1/chat/completions"
    try:
        response = requests.post(openaiApi, headers = headers, data = json.dumps(payload))
        response_data = json.loads(response.content.decode('utf-8'))
        text = response_data['choices'][0]['message']['content'].lstrip()
    except Exception as e:
        logger.warning(e)
        text = "ただいまシステム障害が発生しています。再度お試しください。"

    return text

def putDB(id,text):
    dynamodb = boto3.resource('dynamodb')
    
    # 操作したいテーブルを指定
    table = dynamodb.Table('gucchikun')
    
    # データを書き込みます
    table.put_item(
        Item={
            'userid': id,  # Primary key
            'message': text
        }
    )
    
    return True
    
def getDB(id):
    dynamodb = boto3.resource('dynamodb')
    
    # 操作したいテーブルを指定
    table = dynamodb.Table('gucchikun')
    response = table.get_item(
        Key={
            'userid': id
        }
    )
    try:
        res = response['Item']['message']
        if len(res.split("あなた:")) >= 11:
            res = res[res.find("あなた:",6)+len("あなた:"):]
    except:
        res = ""
        
    return res
    
# lambda処理
def lambda_handler(event, context):
    hash = hmac.new(channelSecret.encode('utf-8'), event['body'].encode('utf-8'), hashlib.sha256).digest()
    signature = base64.b64encode(hash)
    xLineSignature = event['headers']['x-line-signature'].encode('utf-8')
    if xLineSignature != signature:
        logger.error('Invalid signatuer.')
        return {
            'statusCode': 200,
            'body': json.dumps('Invalid signatuer.')
        }

    #イベントの確認
    body = json.loads(event['body'])
    history = "test"
    textObject = ""
    for event in body['events']:
        messages = []

        # イベントタイプがメッセージのときのみ反応
        if event['type'] == 'message':
            # イベントタイプがテキストの場合
            if event['message']['type'] == 'text':
                textObject = event['message']['text']
                userId = event['source']['userId']
                history = getDB(userId)
                    
                try:
                    msg = sendOpenAi(textObject, history)
                    messages.append({
                        'type': 'text',
                        'text': msg
                    })
                    putDB(userId, history+"あなた:"+textObject+"AI:"+msg)
                except Exception as e:
                    logger.error(e)
                    messages.append({
                        'type': 'text',
                        'text': "ただいまシステム障害が発生しています。再度お試しください。"
                    })
               
                    
        # イベントタイプがステッカー
        elif event['message']['type'] == 'sticker':
            messages.append({
                    'type': 'text',
                    'text': "スタンプは未対応です。文章に直してから再度送信してください。"
            }) 

        # LINEへ送る準備
        replyApi = "https://api.line.me/v2/bot/message/reply"
        replyHeaders = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + lineAccesstoken
            }
        data = {
            'replyToken': event['replyToken'],
            'messages': messages
        }
    
        
        # LINEにメッセージをPOST
        response = requests.post(replyApi, headers = replyHeaders, data = json.dumps(data), timeout = (3.5, 7.0))