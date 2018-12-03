from __future__ import print_function
import json
import boto3
import time
import decimal
import re
import datetime
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key, Attr

# ALEXA REPLIES
WEIGHT_DOWN = "Ok, you're down %.1f kg since last week."
WEIGHT_UP = "Ok, you've gained %.1f kg since last week."
HISTORY_WEIGHT = "Your average weight was %.1f kg "
WEIGHT_SAVED = "Ok"

#class DecimalEncoder(json.JSONEncoder):
#    def default(self, o):
#        if isinstance(o, decimal.Decimal):
#            if abs(o) % 1 > 0:
#                return float(o)
#            else:
#                return int(o)
#        return super(DecimalEncoder, self).default(o)


def convert_date(amzn_date):
	one_day = re.compile('^(\d{4})-(\d{2})-(\d{2})$')
	week = re.compile('^(\d{4})-W(\d+)$')
	weekend = re.compile('^(\d{4})-W(\d+)-WE$')
	month = re.compile('^(\d{4})-(\d{2})$')
	quater = re.compile('^(\d{4})-Q([1-4])$')
	season = re.compile('^(\d{4})-(SP|WI|FA|SU)$')
	year = re.compile('^(\d{4})$')
	decade = re.compile('^(\d{3})X$')

	regexes = [one_day, week, weekend, month, quater, season, year, decade]

	for i in range(0,8):
		result = regexes[i].match(amzn_date)
		if result:
			break
	if i == 0:
		d_date = datetime.datetime(int(result.group(1)), int(result.group(2)), int(result.group(3)))
		d_date_end = d_date + datetime.timedelta(days=1)
	elif i == 1:
		d_date = datetime.datetime(int(result.group(1)), 1, 1) + datetime.timedelta(weeks=int(result.group(2)))
		d_date_end = d_date + datetime.timedelta(weeks=1)
	elif i == 2:
		d_date = datetime.datetime(int(result.group(1)), 1, 1) + datetime.timedelta(days=6, weeks=int(result.group(2)))
		d_date_end = d_date + datetime.timedelta(days=2)
	elif i == 3:
		d_date = datetime.datetime(int(result.group(1)), int(result.group(2)), 1)
		d_date_end = datetime.datetime(int(result.group(1)), int(result.group(2))+1, 1)
	elif i == 4:
		quater = int(result.group(2))
		d_date = datetime.datetime(int(result.group(1)), 1 + 3 * (quater - 1), 1)
		d_date_end = d_date + datetime.timedelta(days=90) # This is not quite accurate
	elif i == 5:
		season_mapping = {'SP':3, 'WI':12, 'FA':9, 'SU':6}
		month = season_mapping[result.group(2)]
		d_date = datetime.datetime(int(result.group(1)), month, 1)
		d_date_end = d_date + datetime.timedelta(days=90)
	elif i == 6:
		d_date = datetime.datetime(int(result.group(1)), 1, 1)
		d_date_end = d_date + datetime.timedelta(days=365)
	elif i == 7:
		year = result.group(1) + '0'
		d_date = datetime.datetime(int(year), 1, 1)
		d_date_end = d_date + datetime.timedelta(days=365*10)
	
	return [d_date,d_date_end]


def handle_session_end_request():
    card_title = "Canceled"
    speech_output = "Action canceled! "
    # Setting this to true ends the session and exits the skill.
    should_end_session = True
    return build_response({}, build_speechlet_response(
        card_title, speech_output, None, should_end_session))


def build_speechlet_response(title, output, reprompt_text, should_end_session):
    """
    Build a speechlet JSON representation of the title, output text, 
    reprompt text & end of session
    """
    return {
        'outputSpeech': {
            'type': 'PlainText',
            'text': output
        },
        'card': {
            'type': 'Simple',
            'title': title,
            'content': output
        },
        'reprompt': {
            'outputSpeech': {
                'type': 'PlainText',
                'text': reprompt_text
            }
        },
        'shouldEndSession': should_end_session
    }


def build_response(session_attributes, speechlet_response):
    """
    Build the full response JSON from the speechlet response
    """
    return {
        'version': '1.0',
        'sessionAttributes': session_attributes,
        'response': speechlet_response
    }


def on_intent(intent_request, session, context):

    intent = intent_request['intent']
    intent_name = intent_request['intent']['name']
    userid = context['System']['user']['userId']
    
    if intent_name == 'add_weight':
        return add_weight_action(intent_request,userid)
    elif intent_name == 'check_weight':
        return get_weight_action(intent_request,userid)
    elif intent_name == "AMAZON.CancelIntent" or intent_name == "AMAZON.StopIntent":
        return handle_session_end_request()
    else:
        raise ValueError("Invalid intent")

def get_avg_weight(start_date,end_date,userid):
    ddb_t = boto3.resource("dynamodb").Table("weights")
    try:
        last_weights = ddb_t.query(
            KeyConditionExpression=Key('date').between(
                decimal.Decimal(start_date.strftime('%s')), 
                decimal.Decimal(end_date.strftime('%s'))
                ) & Key('clientid').eq(userid)
        )
        if len(last_weights['Items']) > 0:
            weight_sum = 0
            num_weights = len(last_weights['Items'])
            for item in last_weights['Items']:
                weight_sum += float(item['weight'])  
            avg_weight = weight_sum/num_weights
        else:
            raise ValueError("No weight data found for the selected period %s %s" %(start_date,end_date))
    except ClientError as e:
        print(e.response['Error']['Message'])
        return None
    except ValueError as e:
        print(e)
        return None
    return avg_weight

def get_weight_action(intent_request,userid):
    try:
        amzn_timerange = intent_request['intent']['slots']['timerange']['value']
        if not amzn_timerange:
            raise ValueError('Empty date range')
    except ValueError:
        message = "Invalid date format" 
        card_title = "Error"        
    timerange = convert_date(amzn_timerange)
    avg_weight = get_avg_weight(timerange[0],timerange[1], userid)
    if avg_weight:
        card_title = "Success"
        message = HISTORY_WEIGHT % avg_weight
    else:
        card_title = "There was a problem"
        message = "I don't have your weight data for that period"
    return build_response({}, build_speechlet_response(card_title, message, None, True))

def add_weight_action(intent_request,userid):
    date = int(time.time())
    ddb_t = boto3.resource("dynamodb").Table("weights")
    slots = intent_request['intent']['slots']
    if 'fraction' in slots and 'integer' in slots: 
        if slots['integer']['value'] is not None and slots['fraction']['value'] is not None:
            weight = slots['integer']['value'] + '.' + slots['fraction']['value']
    elif 'integer' in slots:
        if slots['integer']['value'] is not None:
            weight = slots['integer']['value']
    else:
        message = "Invalid weight format" 
        card_title = "Error"   
        return build_response({}, build_speechlet_response(card_title, message, None, True))
    last_week_start_date = datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday(), weeks=1) 
    last_week_end_date = datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday())
    avg_last_week_weight = get_avg_weight(last_week_start_date,last_week_end_date,userid)
    try:
        response = ddb_t.put_item(
            Item = {
                'date': date,
                'clientid': userid,
                'weight': decimal.Decimal(weight)
            }
        )
        if avg_last_week_weight:
            weight_diff = float(weight) - avg_last_week_weight
            if weight_diff < 0:
                message = WEIGHT_DOWN % abs(weight_diff)
            else:
                message = WEIGHT_UP % abs(weight_diff)
        else:
            message = WEIGHT_SAVED
        card_title = "Success"
    except ClientError as e:
        print(e.response['Error']['Message'])
        message = "There was a problem saving your weight"
        card_title = "Error"
    return build_response({}, build_speechlet_response(card_title, message, None, True))

def lambda_handler(event, context):

    print("event.session.application.applicationId=" +
          event['session']['application']['applicationId'])
          
    if event['request']['type'] == "IntentRequest":
        print (event['request'], event['session'], event['context'])
        return on_intent(event['request'], event['session'], event['context'])


