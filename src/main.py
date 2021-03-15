# argparse
import argparse
parser = argparse.ArgumentParser(
    description='Loads social media posts on sports teams and uploads them to' 
    + ' AWS for further processing via Glue & Athena.')
parser.add_argument(
    '-r',
    '--twitter_results_per_page', 
    metavar='N', 
    type=int, 
    default=100,
    help='The number of Twitter results to retrieve for every page request')
parser.add_argument(
    '-m',
    '--twitter_max_results', 
    metavar='N',
    type=int, 
    default=100,
    help='The maximum number of Twitter results to retrieve per item')
args = parser.parse_args()

RESULTS_PER_PAGE = args.twitter_results_per_page
MAX_RESULTS_PER_ITEM = args.twitter_max_results

# import libraries
import os
import requests
import json
import ast
import yaml
import boto3
from datetime import datetime
from time import gmtime, strftime

# AWS clients
s3_client = boto3.client('s3')

# environment variables
storage_bucket = ''
twitter_bearer_token = ''

# supported social media platforms
supported_platforms = [
    'Twitter'
]

# helpers
def load_env_config():
    if not os.environ.get('CONFIG_SETUP'):
        with open('config.yaml') as file:
            config = yaml.safe_load(file)
            os.environ.update(config)
        
def load_league_data(league_file):
    with open(league_file) as file:
        return yaml.safe_load(file)

def clean_text(text):
    '''
    Formats text nicely for pandas by interpreting/replacing problematic characters.
    '''
    return text.replace("\n", "\\n")

# Twitter helpers
def create_twitter_url(
    entity,
    max_results=10, 
    next_token=None,
    query_args="-is:retweet lang:en -%23nbatopshot",
    tweet_fields="created_at,context_annotations,entities,public_metrics"):
    '''
    Constructs the Twitter URL to query against a given Twitter entity.
    '''
    if max_results > RESULTS_PER_PAGE:
        max_results = RESULTS_PER_PAGE
    query_args = " " + query_args

    query_args_fmt = "query=entity:\"{}\"{}".format(entity, query_args)
    max_results_fmt = "max_results={}".format(max_results)
    tweet_fields_fmt = "tweet.fields={}".format(tweet_fields)
    next_token_fmt = "&next_token={}".format(next_token) if next_token else ""

    url = "https://api.twitter.com/2/tweets/search/recent?{}&{}&{}{}".format(
        query_args_fmt,
        max_results_fmt,
        tweet_fields_fmt,
        next_token_fmt
    )
    return url

def twitter_auth_and_connect(bearer_token, url):
    '''
    Executes the given Twitter API call and returns the response.
    '''
    headers = {"Authorization": "Bearer {}".format(bearer_token)}
    response = requests.request("GET", url, headers=headers)
    return response.json()

# social media platform data collection
def get_team_data_from_twitter(team):
    data = []
    results_counted = 0
    next_token = None

    while results_counted < MAX_RESULTS_PER_ITEM:
        # load tweets
        url = create_twitter_url(
            entity=team, 
            max_results=RESULTS_PER_PAGE, 
            next_token=next_token
        )
        res_twitter = twitter_auth_and_connect(twitter_bearer_token, url)

        # add data
        if 'data' in res_twitter:
            data.extend(res_twitter['data'])

        # end loop early if there is no next_token
        results_counted += res_twitter['meta']['result_count']
        if 'next_token' in res_twitter['meta']:
            next_token = res_twitter['meta']['next_token']
        else:
            break

    return data


# team data collection
def write_team_data(league, team, platform='Twitter', output_file='tmp.json'):
    print("Processing " + team + " data from " + platform + "...")
    data = []
    # Twitter
    if platform == 'Twitter':
        data = get_team_data_from_twitter(team)

    # write json output
    with open(output_file, 'a') as outfile:
        for data_point in data: 
            # add columns for league and team name
            data_point['league'] = league
            data_point['team'] = team
            outfile.write(json.dumps(data_point) + '\n')
   
def write_all_team_data(
    league, 
    teams, 
    platform='Twitter', 
    output_file='tmp.json'):
    data = []
    for i in range(len(teams)):
        team = teams[i]
        write_team_data(
            league, 
            team, 
            platform=platform, 
            output_file=output_file)

    return data

# main
def main():
    # set global variables
    global storage_bucket
    global twitter_bearer_token

    # set environment variables
    load_env_config()
    source_data_file = os.environ.get('DATA_FILE')
    storage_bucket = os.environ.get('STORAGE_BUCKET')
    twitter_bearer_token = os.environ.get('TWITTER_BEARER_TOKEN')

    # load data file
    data = load_league_data(source_data_file)
    league = data['league']
    print("Loading data for the league: " + league)
    teams = data['teams']

    # load data for each supported social media platform
    for platform in supported_platforms:
        print("Started collecting " + platform + " data...")

        ### Team Data Start
        print("Collecting " + platform + " team data...")
        start_time = strftime("%Y-%m-%d-%H-%M-%S", gmtime())
        output_file = start_time + ".json"

        write_all_team_data(
            league, 
            teams, 
            platform=platform, 
            output_file=output_file)
        print("Finished collecting " + platform + " team data!")

        # upload file to S3
        s3_key = platform \
            + "/" \
            + league \
            + "/" \
            + strftime("%Y/%m/%d/%H-%M-%S", gmtime()) + ".json"
        s3_client.upload_file(
            Filename=output_file,
            Bucket=storage_bucket,
            Key=s3_key
        )
        print("Uploaded " 
            + platform 
            + " team data results to s3://" + storage_bucket + "/" + s3_key)
        ### Team Data End

        print("Finished collecting " + platform + " data!")

    print("Finished " + league + " data collection!")

if __name__ == "__main__":
    main()