# import os
import codecs
import sys
# import re
import os
# import flask
import numpy as np
# import pandas as pd
# import scipy
from keras_bert import load_trained_model_from_checkpoint, Tokenizer
# import tensorflow as tf


"""### Global variables

Let's specify some global variables to hold things like paths.
Globals in python are always written in all caps.
That makes it easier to find them and replace them with local variables later.
Local variables make your code more modular, easier to reuse and maintain.
"""

MARKER = 'unk'         # our abbreviated UNKOWN word marker (blank)
MASK_TOKEN = '[MASK]'  # defined by the BERT model

BERT_MODEL_CASED = False
BERT_MODELS_DIR = "/home/msoc/apps/unredactor/unredactor/app/models/uncased_L-12_H-768_A-12"

BERT_MODEL_DATE = "2018_10_18"
BERT_MODEL_NAME = "uncased_L-12_H-768_A-12"

BERT_MODEL_DIR = "$BERT_MODELS_DIR/$BERT_MODEL_NAME"
BERT_MODEL_ZIP = "$BERT_MODEL_DIR.zip"
UNZIPPED_MODEL_PATH = os.path.expanduser("~/apps/unredactor/unredactor/app/models/uncased_L-12_H-768_A-12")
CONFIG_PATH = "$UNZIPPED_MODEL_PATH/bert_config.json"
CHECKPOINT_PATH = "$UNZIPPED_MODEL_PATH/bert_model.ckpt"
DICT_PATH = "$UNZIPPED_MODEL_PATH/vocab.txt"

global P
P = None


class NLPPipeline(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for k, v in self.items():
            setattr(self, k, v)


def load_pipeline(unzipped_model_path=UNZIPPED_MODEL_PATH, cased=BERT_MODEL_CASED):
    if len(sys.argv) != 4:
        print('python load_model.py CONFIG_PATH CHECKPOINT_PATH DICT_PATH')
        print('CONFIG_PATH:     UNZIPPED_MODEL_PATH/bert_config.json')
        print('CHECKPOINT_PATH: UNZIPPED_MODEL_PATH/bert_model.ckpt')
        print('DICT_PATH:       UNZIPPED_MODEL_PATH/vocab.txt')

    config_path, checkpoint_path, dict_path = (unzipped_model_path + '/bert_config.json',
                                               unzipped_model_path + '/bert_model.ckpt',
                                               unzipped_model_path + '/vocab.txt')

    model = load_trained_model_from_checkpoint(config_path, checkpoint_path, training=True)
    model.summary(line_length=120)

    token_dict = {}
    with codecs.open(dict_path, 'r', 'utf8') as reader:
        for line in reader:
            token = line.strip()
            token_dict[token] = len(token_dict)
    token_dict_rev = {v: k for k, v in token_dict.items()}
    if cased:
        print('***************CASED TOKENIZER*******************')
    else:
        print('***************uncased tokenizer*******************')
    tokenizer = Tokenizer(token_dict, cased=cased)

    return NLPPipeline(model=model, token_dict=token_dict, token_dict_rev=token_dict_rev, tokenizer=tokenizer)


P = load_pipeline()


def find_repeated_substring(text, substring=MARKER, max_occurences=32):
    substring = substring or MARKER
    start = text.find(substring)
    stop = start + len(substring)
    starts = []
    for i in range(max_occurences):
        if not (start > -1 and stop <= len(text) - len(substring) + 1):
            break
        # print(start, stop)
        if len(starts):
            stop = starts[-1] + len(substring)
            starts.append(stop + start)
        else:
            starts = [start]
        # print(start, stop)
        start = text[stop:].find(substring)
        if start < 0 and len(starts) > 1:
            return starts[:-1]
        # print(start, stop)
        # print(starts)
    return starts


def unredact_tokens(prefix_tokens=[], suffix_tokens=[], num_redactions=5, actual_tokens=None):
    global P
    if not P:
        P = load_pipeline()
    tokens = list(prefix_tokens) + [MASK_TOKEN] * num_redactions + list(suffix_tokens)
    tokens = tokens[:512]
    tokens_original = tokens.copy()

    indices = np.asarray([[P.token_dict[token] for token in tokens] + [0] * (512 - len(tokens))])
    segments = np.asarray([[0] * len(tokens) + [0] * (512 - len(tokens))])
    masks = np.asarray([[0] * 512])
    redactions = []
    for i, t in enumerate(tokens):
        if t == MASK_TOKEN:
            redactions.append(i - 1)
            masks[0][i] = 1

    predicts = P.model.predict([indices, segments, masks])[0]
    predicts = np.argmax(predicts, axis=-1)
    predictions_parameterized = list(
        map(lambda x: P.token_dict_rev[x],
            [x for (j, x) in enumerate(predicts[0]) if j - 1 in redactions])
        )
    print(f'Predictions: {predictions_parameterized}')

    all_actual_tokens = []
    actual_tokens = actual_tokens or [MASK_TOKEN] * num_redactions
    k = 0
    for i, masked_tok in enumerate(tokens_original):
        if i - 1 in redactions:
            all_actual_tokens.append(actual_tokens[k])
            k += 1
        else:
            all_actual_tokens.append(masked_tok)
    print(f'    Actual: {[tok for (i, tok) in enumerate(all_actual_tokens) if i - 1 in redactions]}')

    return (predictions_parameterized, tokens)


def unredact_bert(text, get_words=False, marker=MARKER, redacted_tokens=None):
    global P
    if not P:
        P = load_pipeline()
    marker = marker or 'unk'

    redactions = find_repeated_substring(text, substring=marker)
    if not redactions:
        print('No redactions found')
        return redactions

    start, stop = redactions[0], redactions[-1] + len(marker)
    prefix, suffix = text[:start], text[stop:]
    prefix_tokens = P.tokenizer.tokenize(prefix)[:-1]
    suffix_tokens = P.tokenizer.tokenize(suffix)[1:]
    unredacted_tokens, all_tokens = unredact_tokens(
        prefix_tokens=prefix_tokens,
        suffix_tokens=suffix_tokens,
        num_redactions=len(redactions),
        actual_tokens=redacted_tokens)

    print(f'all_tokens: {all_tokens}')
    print(f'unredacted_tokens: {unredacted_tokens}')

    j = 0
    count_correct = 0
    for (i, tok) in enumerate(all_tokens):
        if tok == '[MASK]' and j < len(unredacted_tokens):
            all_tokens[i] = unredacted_tokens[j]
            if redacted_tokens:
                count_correct += int(unredacted_tokens[j] == redacted_tokens[j])
            j += 1
    if redacted_tokens and redacted_tokens[0] != MASK_TOKEN:
        print(f' {count_correct} out of {len(unredacted_tokens)} redacted tokens were correctly predicted by BERT.')

    unredacted_text = ' '.join(all_tokens)

    if get_words:
        return unredacted_text, unredacted_tokens

    return unredacted_text


# unredacted_text, unredacted_words = unredact_bert("To be or not to unk, that is the question.", get_words=True)
