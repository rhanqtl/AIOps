# -*- coding: utf-8 -*-

"""
Description : This file implements the Drain algorithm for raw_log_data parsers
Author      : LogPAI team
License     : MIT
"""

import logging
import regex as re
import os
import numpy as np
import pandas as pd
import hashlib
from datetime import datetime

from exceptions import NoSuchLogDataException
from storage.log_storage.log_storage import LogStorage


class Incrementer:
    def __init__(self, init_val=1):
        self.init_val = init_val
        self.val = init_val

    def __call__(self):
        ret = self.val
        self.val += 1
        return ret


class LogCluster:
    def __init__(self, logTemplate='', logIDL=None):
        self.logTemplate = logTemplate
        if logIDL is None:
            logIDL = []
        self.logIDL = logIDL


class Node:
    def __init__(self, childD=None, depth=0, digitOrtoken=None):
        if childD is None:
            childD = dict()
        self.childD = childD
        self.depth = depth
        self.digitOrtoken = digitOrtoken


class LogParser:
    def __init__(self,
                 log_format,
                 data,
                 structured_log_store: LogStorage,
                 event_template_store: LogStorage,
                 depth=4,
                 st=0.4,
                 maxChild=100,
                 rex=None,
                 keep_para=True):
        """
        Attributes
        ----------
            rex : regular expressions used in preprocessing (step1)
            path : the input path stores the input raw_log_data file name
            depth : depth of all leaf nodes
            st : similarity threshold
            maxChild : max number of children of an internal node
            logName : the name of the input file containing raw raw_log_data messages
            savePath : the output path stores the file containing structured logs
        """
        if rex is None:
            rex = []
        self.data = data
        self.structured_log_store = structured_log_store
        self.event_template_store = event_template_store
        # self.savePath = outdir
        self.depth = depth - 2
        self.st = st
        self.maxChild = maxChild
        self.logName = None
        self.df_log = None
        self.log_format = log_format
        self.rex = rex
        self.keep_para = keep_para

    def _tree_search(self, rn, seq):
        retLogClust = None

        seqLen = len(seq)
        if seqLen not in rn.childD:
            return retLogClust

        parentn = rn.childD[seqLen]

        currentDepth = 1
        for token in seq:
            if currentDepth >= self.depth or currentDepth > seqLen:
                break

            if token in parentn.childD:
                parentn = parentn.childD[token]
            elif '<*>' in parentn.childD:
                parentn = parentn.childD['<*>']
            else:
                return retLogClust
            currentDepth += 1

        logClustL = parentn.childD

        retLogClust = self.fastMatch(logClustL, seq)

        return retLogClust

    def addSeqToPrefixTree(self, rn, logClust):
        seqLen = len(logClust.logTemplate)
        if seqLen not in rn.childD:
            firtLayerNode = Node(depth=1, digitOrtoken=seqLen)
            rn.childD[seqLen] = firtLayerNode
        else:
            firtLayerNode = rn.childD[seqLen]

        parentn = firtLayerNode

        currentDepth = 1
        for token in logClust.logTemplate:

            # Add current raw_log_data cluster to the leaf node
            if currentDepth >= self.depth or currentDepth > seqLen:
                if len(parentn.childD) == 0:
                    parentn.childD = [logClust]
                else:
                    parentn.childD.append(logClust)
                break

            # If token not matched in this layer of existing tree.
            if token not in parentn.childD:
                if not self._has_numbers(token):
                    if '<*>' in parentn.childD:
                        if len(parentn.childD) < self.maxChild:
                            newNode = Node(depth=currentDepth + 1, digitOrtoken=token)
                            parentn.childD[token] = newNode
                            parentn = newNode
                        else:
                            parentn = parentn.childD['<*>']
                    else:
                        if len(parentn.childD)+1 < self.maxChild:
                            newNode = Node(depth=currentDepth+1, digitOrtoken=token)
                            parentn.childD[token] = newNode
                            parentn = newNode
                        elif len(parentn.childD)+1 == self.maxChild:
                            newNode = Node(depth=currentDepth+1, digitOrtoken='<*>')
                            parentn.childD['<*>'] = newNode
                            parentn = newNode
                        else:
                            parentn = parentn.childD['<*>']

                else:
                    if '<*>' not in parentn.childD:
                        newNode = Node(depth=currentDepth+1, digitOrtoken='<*>')
                        parentn.childD['<*>'] = newNode
                        parentn = newNode
                    else:
                        parentn = parentn.childD['<*>']

            # If the token is matched
            else:
                parentn = parentn.childD[token]

            currentDepth += 1

    # seq1 is template
    def seqDist(self, seq1, seq2):
        assert len(seq1) == len(seq2)
        simTokens = 0
        numOfPar = 0

        for token1, token2 in zip(seq1, seq2):
            if token1 == '<*>':
                numOfPar += 1
                continue
            if token1 == token2:
                simTokens += 1

        retVal = float(simTokens) / len(seq1)

        return retVal, numOfPar

    def fastMatch(self, logClustL, seq):
        retLogClust = None

        maxSim = -1
        maxNumOfPara = -1
        maxClust = None

        for logClust in logClustL:
            curSim, curNumOfPara = self.seqDist(logClust.logTemplate, seq)
            if curSim>maxSim or (curSim==maxSim and curNumOfPara>maxNumOfPara):
                maxSim = curSim
                maxNumOfPara = curNumOfPara
                maxClust = logClust

        if maxSim >= self.st:
            retLogClust = maxClust

        return retLogClust

    def getTemplate(self, seq1, seq2):
        assert len(seq1) == len(seq2)
        retVal = []

        i = 0
        for word in seq1:
            if word == seq2[i]:
                retVal.append(word)
            else:
                retVal.append('<*>')

            i += 1

        return retVal

    def output_result(self, log_clusters):
        logging.info("Writing result ...")

        try:
            existing_events = self.event_template_store.get()
        except NoSuchLogDataException:
            existing_events = pd.DataFrame(columns=["EventId", "EventTemplate", "Occurrences"])
        next_id = len(existing_events) + 1

        log_templates = [0] * self.df_log.shape[0]
        log_template_ids = [0] * self.df_log.shape[0]
        events = []
        for log_cluster in log_clusters:
            template_str = ' '.join(log_cluster.logTemplate)
            # template_id = hashlib.md5(template_str.encode('utf-8')).hexdigest()[0:8]
            t = existing_events[existing_events["EventTemplate"] == template_str]
            exists = len(t) != 0
            if exists:
                template_id = int(t["EventId"])
            else:
                template_id = next_id
                next_id = next_id + 1
            for logID in log_cluster.logIDL:
                logID -= 1
                log_templates[logID] = template_str
                log_template_ids[logID] = template_id
            occurrence = len(log_cluster.logIDL)
            if not exists:
                events.append([template_id, template_str, occurrence])

        df_event = pd.DataFrame(events, columns=['EventId', 'EventTemplate', 'Occurrences'])
        self.event_template_store.save(df_event)

        self.df_log['EventId'] = log_template_ids
        self.df_log['EventTemplate'] = log_templates
        if self.keep_para:
            self.df_log["ParameterList"] = self.df_log.apply(self._get_parameter_list, axis=1)
        self.structured_log_store.save(self.df_log)
        # self.df_log.to_csv(os.path.join(self.savePath, self.logName + '_structured.csv'), index=False)

        # inc = Incrementer()
        # occ_dict = dict(self.df_log['EventTemplate'].value_counts())
        # df_event = pd.DataFrame()
        # df_event['EventTemplate'] = self.df_log['EventTemplate'].unique()
        # # df_event['EventId'] = df_event['EventTemplate'].map(lambda x: hashlib.md5(x.encode('utf-8')).hexdigest()[0:8])
        # df_event['EventId'] = df_event['EventTemplate'].map(lambda _: inc())
        # df_event['Occurrences'] = df_event['EventTemplate'].map(occ_dict)
        # self.event_template_store.save(df_event)
        # df_event.to_csv(
        #     os.path.join(self.savePath, self.logName + '_templates.csv'),
        #     index=False, columns=["EventId", "EventTemplate", "Occurrences"])

    def print_tree(self, node, dep):
        pStr = ''
        for i in range(dep):
            pStr += '\t'

        if node.depth == 0:
            pStr += 'Root'
        elif node.depth == 1:
            pStr += '<' + str(node.digitOrtoken) + '>'
        else:
            pStr += node.digitOrtoken

        print(pStr)

        if node.depth == self.depth:
            return 1
        for child in node.childD:
            self.print_tree(node.childD[child], dep + 1)

    def parse(self):
        start_time = datetime.now()
        rootNode = Node()
        logCluL = []

        self.load_data()

        count = 0
        for idx, line in self.df_log.iterrows():
            logID = line['LineId']
            logmessageL = self.preprocess(line['Content']).strip().split()
            # logmessageL = filter(lambda x: x != '', re.split('[\s=:,]', self.preprocess(line['Content'])))
            matchCluster = self._tree_search(rootNode, logmessageL)

            # Match no existing raw_log_data cluster
            if matchCluster is None:
                newCluster = LogCluster(logTemplate=logmessageL, logIDL=[logID])
                logCluL.append(newCluster)
                self.addSeqToPrefixTree(rootNode, newCluster)

            # Add the new raw_log_data message to the existing cluster
            else:
                newTemplate = self.getTemplate(logmessageL, matchCluster.logTemplate)
                matchCluster.logIDL.append(logID)
                if ' '.join(newTemplate) != ' '.join(matchCluster.logTemplate):
                    matchCluster.logTemplate = newTemplate

            count += 1
            if count % 1000 == 0 or count == len(self.df_log):
                print('Processed {0:.1f}% of raw_log_data lines.'.format(count * 100.0 / len(self.df_log)))

        # if not os.path.exists(self.savePath):
        #     os.makedirs(self.savePath)

        self.output_result(logCluL)

        print('Parsing done. [Time taken: {!s}]'.format(datetime.now() - start_time))

    def load_data(self):
        headers, regex = self._generate_log_format_regex(self.log_format)
        self.df_log = self._log_to_data_frame(regex, headers)

    def preprocess(self, line):
        for currentRex in self.rex:
            line = re.sub(currentRex, '<*>', line)
        return line

    def _log_to_data_frame(self, regex, headers):
        """ Function to transform raw_log_data file to DataFrame
        """
        log_messages = []
        line_count = 0
        for line in self.data:
            try:
                match = regex.search(line.strip())
                message = [match.group(header) for header in headers]
                log_messages.append(message)
                line_count += 1
            except Exception:
                pass
        log_df = pd.DataFrame(log_messages, columns=headers)
        log_df.insert(0, 'LineId', None)
        log_df['LineId'] = [i + 1 for i in range(line_count)]
        return log_df

    @staticmethod
    def _generate_log_format_regex(log_format):
        """ Function to generate regular expression to split raw_log_data messages
        """
        headers = []
        splitters = re.split(r'(<[^<>]+>)', log_format)
        regex = ''
        for k in range(len(splitters)):
            if k % 2 == 0:
                splitter = re.sub(' +', '\\\s+', splitters[k])
                regex += splitter
            else:
                header = splitters[k].strip('<').strip('>')
                regex += '(?P<%s>.*?)' % header
                headers.append(header)
        regex = re.compile('^' + regex + '$')
        return headers, regex

    @staticmethod
    def _get_parameter_list(row):
        template_regex = re.sub(r"<.{1,5}>", "<*>", row["EventTemplate"])
        if "<*>" not in template_regex:
            return []
        template_regex = re.sub(r'([^A-Za-z0-9])', r'\\\1', template_regex)
        template_regex = re.sub(r'\\ +', r'\s+', template_regex)
        template_regex = "^" + template_regex.replace("\<\*\>", "(.*?)") + "$"
        parameter_list = re.findall(template_regex, row["Content"])
        parameter_list = parameter_list[0] if parameter_list else ()
        parameter_list = list(parameter_list) if isinstance(parameter_list, tuple) else [parameter_list]
        return parameter_list

    @staticmethod
    def _has_numbers(s):
        return any(char.isdigit() for char in s)