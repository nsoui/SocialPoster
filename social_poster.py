#!/usr/bin/env python3


# from urllib import request
import requests
import sys, json
from datetime import datetime

import argparse
import logging

# Needed to schedule the posts
import schedule, time
import re
import urllib.parse

with open("config.json", "r") as f:
    config = json.load(f)


class CustomFormatter(logging.Formatter):

    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format = "%(asctime)s,%(msecs)d %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s"

    FORMATS = {
        logging.DEBUG: grey + format + reset,
        logging.INFO: grey + format + reset,
        logging.WARNING: yellow + format + reset,
        logging.ERROR: red + format + reset,
        logging.CRITICAL: bold_red + format + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)



class BaseWorker:
    log_levels = {'DEBUG': logging.DEBUG, 'INFO': logging.INFO, 'WARN': logging.WARN, 'ERROR': logging.ERROR,
                  'NONE': logging.NOTSET}

    def __init__(self, args, name, description, additional_args_formats=None):

        self.parser = argparse.ArgumentParser(description)
        self.parser.add_argument("-l", "--log-file", action="store", dest="logFile", default="",
                                help="Writes the log output into the given file")
        self.parser.add_argument("-d", "--debug", action="store", dest="debug", choices=self.log_levels, default="INFO",
                             help="Log level")


        if additional_args_formats is not None:
            for arg, kwargs in additional_args_formats:
                self.parser.add_argument(arg, **kwargs)


        self.args = self.parser.parse_args(args)
        self.__init_logger__(name)

    def __init_logger__(self,name):

        self.logger = logging.getLogger(name)

        self.logger.setLevel(logging.DEBUG)

        # create console handler with a higher log level
        ch = logging.StreamHandler()
        ch.setLevel(self.args.debug)
        ch.setFormatter(CustomFormatter())
        self.logger.addHandler(ch)
        if self.args.logFile != "":
            # create file handler which logs even debug messages
            fh = logging.FileHandler(self.args.logFile, mode="w")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(formatter)
            self.logger.addHandler(fh)


graph_url = 'https://graph.facebook.com/v15.0/'


# Can be extended at https://developers.facebook.com/tools/debug/accesstoken/?access_token=EAAJZBquiAZAwIBAKDwQwtu7CIOxsZC49hubZBuiDQ107BOEKp9xCGwnpb28WCyp16sX2FxE2H4ZCcKQjbi46bGc83kbmVfdSjxsNrV1TKY9f6t9jVJKdJRB8rQ6suN0bAP8AA9vg61HDsJdg9FvOhlmMcSUsobNB8e2SEJ8I4g1WaXIjlBIxZAaRTQnw9Oy3cxZAOC2pvXCTubvfcLndrMZCSK7ttmU4tjkZD&version=v16.0
# long_term_token='EAADFfxQ7XGUBAO1WLVY4Jw18ZBkMHMTVteB4O0Rf7kZALVoHIuji2BT1M9hAjVZBq35C3UKOSFyAeeoHMw2DLHrzbBMz6sToYjM4on0WkPL3Ge93ZAbdQofhu8rVa3wswNU4MZCZAWpERg47nlkXpr36LUoap1UZBZBdDxZAfi7bPcfQoTNJkFYVroK9f3ADTEGEZD'

class SocialPoster(BaseWorker):
    def __init__(self, args):

        additional_args_formats = [
            ('-u', {'action': 'store_true', 'dest': 'update_tokens', 'default': False,
                    'help': 'Will update app tokens from instagram. Will need a short-time token as well generated under https://developers.facebook.com/tools/explorer/'}),
            ('-token', {'action': 'store', 'dest': 'short_time_token', 'default': None, 'required': False,
                    'help': 'Short lived token generated https://developers.facebook.com/tools/explorer/'}),
            ('-hashs', {'action': 'store_true', 'dest': 'update_hashs', 'default': False,
                    'help': 'Will update the hash,json file with the hashtags of the site and return'}),
            ('-url', {'action': 'store', 'dest': 'url', 'default': None, 'required': False,
                    'help': 'Temporarily overwrite the site url for debug purposes'}),
            ('-t', {'action': 'store_true', 'dest': 'testrun', 'default': False,
                    'help': 'Run a test process, does not modify anything on the disk'}),
            ('-now', {'action': 'store_true', 'dest': 'now', 'default': False,
                    'help': 'Post the pictures straight ahead instead of planning them for a daily upload'}),
            (("-newerthan"), {"action": "store", "dest": "newerthan", "default": None,
                               "help": r"Only process pictures newer than the given timestamp in the format YYYYMMDD"}),
            (("-olderthan"), {"action": "store", "dest": "olderthan", "default": None,
                               "help": r"Only process pictures older than the given timestamp in the format YYYYMMDD"}),
            ('-paths', {'nargs': '+', 'required': False, 'help': 'Specific posts to process'})                   
            ]

        BaseWorker.__init__(self, args=args, name=r"Social Poster", description=r"Post images automatically",
                            additional_args_formats=additional_args_formats)
        
        if self.args.newerthan is not None and self.args.newerthan != '':
            self.args.newerthan_ts = datetime.strptime(self.args.newerthan, '%Y%m%d')
        else:
            self.args.newerthan_ts = None

        if self.args.olderthan is not None and self.args.olderthan != '':
            self.args.olderthan_ts = datetime.strptime(self.args.olderthan, '%Y%m%d')
        else:
            self.args.olderthan_ts = None
        
        self.posts_list = []

        if self.args.url is not None:
            self.logger.debug('Overwriting the site url with ' + self.args.url)
            config['site']['url'] = self.args.url

    
        

    @staticmethod
    def printProgress(progress):
        print("[%d%%]" % progress)

    
    def __getHashtags(self, tags):
        r = set()
        hashs = self.__read_hashtags()
        for tag in tags:
            if tag in hashs:
                r.update( hashs[tag] )
            else:
                self.logger.warning("{} is missing from the hash table, adding it as-is".format(tag))
                r.add( re.sub(r'[^\w_]', '', tag.lower()))
                r.add( re.sub(r'[^\w]', '_', tag.lower()))
        return r

        
        return r

    def __get_url(self, url, method='get', params=None, info=''):
        if info != '':
            self.logger.info(info)
        if method=='get':
            r = requests.get(url, params=params)
        elif method=='post':
            r = requests.post(url, params=params)
        self.logger.debug(r.url)
        r = r.json()
        self.logger.debug(r)
        return r

    
    def __update_tokens(self):
        payload = {
                'client_id': config['insta']['app_id'],
                'client_secret': config['insta']['app_secret'],
                'fb_exchange_token': self.args.short_time_token,
                'grant_type': 'fb_exchange_token'
                }

        r = self.__get_url( graph_url + 'oauth/access_token?' , params=payload, info='Requesting a long term token')
        config['long_term_token'] = r['access_token']
        
        # ------------------ Step 2 --------------------------
        # Getting the instagram business ID 
        url = graph_url + config['insta']['facebook_page_id']
        param = dict()
        param['access_token'] = config['long_term_token']
        param['fields'] = 'instagram_business_account' # 'access_token'
        r = self.__get_url( url=url , params=param, info='Requesting the FB page User ID')
        config['ig_business_account_id'] = r['instagram_business_account']['id']
        self.logger.debug("Updating the config file with the new tokens")
        with open(f"config.json", "w") as f:
            json.dump(config, f, indent=4)
        

    def __post_image(self):
        post = self.posts_list.pop(0)
        url = graph_url + config['ig_business_account_id'] + '/media'
        param = dict()
        param['access_token'] = config['long_term_token']
        param['caption'] = post['caption']
        param['image_url'] =  post['image_url']
        self.logger.info('Posting the picture {}\n===========================Caption:===============\n{}\n\n=================Hashtags=============\n{}'.format(post['image_url'], post['caption'], post['hashtags']))
        
        if not self.args.testrun:
            r = self.__get_url(url, method='post', params=param)
            creation_id = r['id']
            url = graph_url + config['ig_business_account_id'] + '/media_publish'
            param = dict()
            param['access_token'] = config['long_term_token']
            param['creation_id'] = creation_id
            r = self.__get_url(url, method='post', params=param)
            media_id = r['id']
            url = graph_url + media_id +'/comments'
            while len(post['hashtags']) > 0:
                comment = []
                while len(post['hashtags']) > 0 and len(comment) < 30:
                    comment.append( post['hashtags'].pop())
                param = dict()
                param['message'] = ' '.join(comment)
                param['access_token'] = config['long_term_token']
                r = self.__get_url(url, method='post', params=param)
            return r
    
    def __get_sorted_tags(self):
        tags = self.__get_url( config['site']['url'] + config['site']['tags'])
        tagslist = [(key, value['size']) for key, value in tags.items()]
        tagslist = sorted(tagslist, key= lambda x : x[1])
        self.logger.debug('Got the following sorted tags from the site:\n' + "\n".join([ '{}({})'.format(key, size) for key, size in tagslist ]) )
        return tags
    
    def __read_hashtags(self):
        with open("hash.json", "r") as f:
            r = json.load(f)
        return r

    def __update_hashs(self, sorted_tags):
        original_hashtags = self.__read_hashtags()
        for tag in sorted_tags:
            if tag not in original_hashtags:
                self.logger.debug("Adding the tag {} to the list".format(tag) )
                original_hashtags[tag] = []
        self.logger.debug(original_hashtags)
        if not self.args.testrun: 
            with open(f"hash-updated.json", "w") as f:
                json.dump(original_hashtags, f, indent=4)


    def run(self, call_back_to_report_progress_percentage=None):
        # Do we need new tokens?
        if self.args.update_tokens:
            if self.args.short_term_token is None:
                self.logger.error("A shot term token is needed. Go to https://developers.facebook.com/tools/explorer/")
                return False
            else:
                self.__update_tokens()

        if self.args.update_hashs:
            tags = self.__get_sorted_tags()
            self.__update_hashs(tags)
            return True

        # Get the lates pictures
        url = urllib.parse.urljoin( config['site']['url'], config['site']['posts'])
        posts = self.__get_url(url)
        if self.args.paths is not None:
            self.logger.info('Searching for {} specific paths within {} posts'.format(len(self.args.paths), len(posts)) )
            self.logger.info(self.args.paths)
        for post in reversed(posts):
                post['ts'] = datetime.strptime(post['date'], '%Y-%m-%d')
                if self.args.newerthan_ts is not None and self.args.newerthan_ts != '' and self.args.newerthan_ts >= post['ts']:
                    self.logger.debug("Skipping too old file %s" % post['title'])
                    continue
                if self.args.olderthan_ts is not None and self.args.olderthan_ts != '' and self.args.olderthan_ts <= post['ts']:
                    self.logger.debug("Skipping too new file %s" % post['title'])
                    continue

                post['full_url'] = urllib.parse.urljoin(config['site']['url'], post['url'])

                if self.args.paths is not None and post['full_url'] not in self.args.paths:
                    continue
                
                # This picture will be posted
                post['image_url'] =  'https://souissi.eu/gallery/large/' + post['picture']
                self.logger.info("Gonna post the picture {} taken on {} in {}, {}".format(post['image_url'], post['date'], post['city'], post['country']))
                post['caption'] = post['title'] 
                post['caption'] += '\nShot in {}'.format(post['ts'].strftime("%B %Y")) + ' in {}, {}'.format(post['city'], post['country'])
                post['caption'] += '\n📷 ' + post['camera']
                post['caption'] += '\n🔎 {} @{}mm f/{}'.format(post['lens'], post['focallength'],post['fstop'])
                post['caption'] += '\n💡 {}s iso{}'.format(post['exposure'], post['iso'])                
                post['caption'] += '\n\nFind the original picture with more details at ' + 'https://souissi.eu/' + post['url'] 
                post['caption'] += '\n\nMore of my work at ' + 'https://souissi.eu/'  
                hashtags = self.__getHashtags(post['tags']+[post['city'], post['country'], post['camera'], post['lens']] )
                post['hashtags'] = [ '#'+ h for h in hashtags]
                self.logger.debug('The generated caption is:\n{}'.format(post['caption']))
                self.logger.debug('Posting with {} hashtags:\n{}'.format( len(post['hashtags']), post['hashtags']))
                self.posts_list.append(post)

        if self.args.testrun or self.args.now :
            schedule.every(1).seconds.do(self.__post_image)
        else:
            schedule.every().day.at("21:30").do(self.__post_image)

        while len(self.posts_list) > 0:
            schedule.run_pending()
            time.sleep(1);
        



if __name__ == "__main__":

    pp = SocialPoster(sys.argv[1:])
#    pp.get_tokens()
    pp.run(call_back_to_report_progress_percentage=pp.printProgress)
    sys.exit(0)


