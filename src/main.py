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
    help='The number of Twitter results to retrieve per page request')
parser.add_argument(
    '-m',
    '--twitter_max_results', 
    metavar='N',
    type=int, 
    default=3000,
    help='The maximum number of Twitter results to retrieve')
args = parser.parse_args()

# constants / environment variables
RESULTS_PER_PAGE = args.twitter_results_per_page
MAX_RESULTS = args.twitter_max_results
STORAGE_BUCKET = ''
TWITTER_BEARER_TOKEN = ''

# import libraries
import os
import requests
import json
import ast
import yaml
import boto3
import datetime
from time import gmtime, strftime

# AWS clients
s3_client = boto3.client('s3')

# file helpers
def load_environment_variables():
    if not os.environ.get('ENVIRONMENT_SETUP'):
        # TODO: download config file
        with open('config.yaml') as file:
            config = yaml.safe_load(file)
            os.environ.update(config)
        
def load_data_file(data_file):
    with open(data_file) as file:
        documents = list(yaml.safe_load_all(file))
        version = documents[0]
        data = documents[1]
        return version, data

def load_platforms(platforms_file):
    with open(platforms_file) as file:
        documents = list(yaml.safe_load_all(file))
        version = documents[0]
        data = documents[1]
        return version, data

# S3 helpers 
def upload_results(
    date,
    s3_path='SocialMedia/League',
    results_file='tmp.json'):

    # partition based on start date
    s3_key = s3_path \
        + "/" \
        + date.strftime("%Y/%m/%d/") \
        + results_file

    # upload to S3
    s3_client.upload_file(
        Filename=results_file,
        Bucket=STORAGE_BUCKET,
        Key=s3_key
    )
    print("Uploaded results to s3://" + s3_key)

# Twitter helpers
def create_twitter_url(
    entity,
    start_time='2021-01-00T00:00:00.00Z',
    max_results=10, 
    next_token=None,
    query_args="-is:retweet lang:en -%23nbatopshot",
    tweet_fields="created_at,context_annotations,entities,public_metrics"):
    '''
    Constructs the Twitter API call to collect information about the given 
    entity, dating back to the oldest specified time.
    '''
    if max_results > RESULTS_PER_PAGE:
        max_results = RESULTS_PER_PAGE
    query_args = " " + query_args

    query_args_fmt = "query=entity:\"{}\"{}".format(entity, query_args)
    max_results_fmt = "max_results={}".format(max_results)
    tweet_fields_fmt = "tweet.fields={}".format(tweet_fields)
    start_time_fmt = "start_time={}".format(start_time)
    next_token_fmt = "&next_token={}".format(next_token) if next_token else ""

    url = "https://api.twitter.com/2/tweets/search/recent?{}&{}&{}&{}{}".format(
        query_args_fmt,
        max_results_fmt,
        tweet_fields_fmt,
        start_time_fmt,
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

def write_tweets(
    start_date,
    topic_data,
    output_file='tmp.json'
    ):
    '''
    Collects tweets about the given topic and writes them to the specified 
    output file.
    '''
    # collect tweets
    topic = topic_data['topic']
    results_counted = 0
    next_token = None

    while results_counted < MAX_RESULTS:
        # load tweets
        isotime = start_date.isoformat() + "Z"
        url = create_twitter_url(
            entity=topic,
            start_time=isotime,
            max_results=RESULTS_PER_PAGE, 
            next_token=next_token
        )
        res_twitter = twitter_auth_and_connect(TWITTER_BEARER_TOKEN, url)

        # add data
        if 'data' in res_twitter:
            tweets = res_twitter['data']
            # write output
            with open(output_file, 'a') as outfile:
                for tweet in tweets:
                    outfile.write(json.dumps(tweet) + '\n')

        # end loop early if there is no next_token
        results_counted += res_twitter['meta']['result_count']
        if 'next_token' in res_twitter['meta']:
            next_token = res_twitter['meta']['next_token']
        else:
            break

def collect_and_write_twitter_data(
    data,
    start_date,
    datafile_version=1.0
    ):
    '''
    Aggregates and uploads Twitter data based on the given data template.
    '''
    if datafile_version == 1.0:
        topic = data['topic']
        topic_type = data['type']
        aliases = data['aliases']

        # Twitter API v2 is in JSON format
        #output_time = datetime.datetime.utcnow()
        output_file = strftime("%H-%M-%S", gmtime()) + ".json"

        # write tweets into JSON file
        write_tweets(start_date, topic_data=data, output_file=output_file)

        # upload file to S3 (if there was any info)
        if (os.path.exists(output_file)):
            s3_key_partition = topic
            if topic_type == 'Team':
                s3_key_partition = data['League']
            
            upload_results(
                date=start_date,
                s3_path='Twitter/' + s3_key_partition,
                results_file=output_file
            )
        else:
            print("No Twitter data found")
    else:
        raise(
            "Datafile version " 
            + datafile_version 
            + " is unsupported for Twitter"
        )

# platform helpers
def collect_and_write_all_platform_data_v1_0(
    data,
    platforms_data,
    start_date,
    datafile_version=1.0
    ):
    '''
    Handles the aggregation of data based on version 1.0 platformfiles.
    '''
    platforms = platforms_data['platforms']
    print(str(len(platforms)) + " social media platforms: " + str(platforms))
    for p in platforms:
        print("Collecting " + p + " data...")
        if p == 'Twitter':
            collect_and_write_twitter_data(data, start_date, datafile_version)
        else:
            raise("Social media platform " + p + " is unsupported")

# main
def collect_and_write_data(
    data,
    platforms_data,
    start_date,
    datafile_version=1.0,
    platformfile_version=1.0,
    ):
    '''
    Aggregates social media posts based on a data template, and social media 
    template, then uploads them to AWS.
    '''
    if platformfile_version == 1.0:
        collect_and_write_all_platform_data_v1_0(
            data=data,
            platforms_data=platforms_data,
            start_date=start_date,
            datafile_version=datafile_version
        )
    else:
        raise("Platformfile version " + platformfile_version + " is unsupported")

def main():
    global STORAGE_BUCKET
    global TWITTER_BEARER_TOKEN

    # set environment variables
    load_environment_variables()
    source_data_file = os.environ.get('DATA_FILE')
    platforms_file = os.environ.get('PLATFORMS_FILE')
    STORAGE_BUCKET = os.environ.get('STORAGE_BUCKET')
    TWITTER_BEARER_TOKEN = os.environ.get('TWITTER_BEARER_TOKEN')

    # load data file
    datafile_version, data = load_data_file(source_data_file)
    print("Datafile Version: " + str(datafile_version['version']))

    # load social media platforms file
    platformfile_version, platforms_data = load_platforms(platforms_file)
    print("Platformfile Version: " + str(platformfile_version['version']))

    # start date (past 24 hours)
    start_date = datetime.datetime.utcnow() - datetime.timedelta(days=1)
    print("Retrieving data from " + str(start_date))

    # collect and write data
    collect_and_write_data(
        data=data,
        platforms_data=platforms_data,
        start_date=start_date,
        datafile_version=datafile_version['version'],
        platformfile_version=platformfile_version['version']
    )
    print("Finished collecting all data!")

    ''' load data for each given social media platform
    for platform in social_media_platforms:
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
            Bucket=STORAGE_BUCKET,
            Key=s3_key
        )
        print("Uploaded " 
            + platform 
            + " team data results to s3://" + STORAGE_BUCKET + "/" + s3_key)
        ### Team Data End

        print("Finished collecting " + platform + " data!")
    
    print("Finished " + league + " data collection!")
    '''

if __name__ == "__main__":
    main()