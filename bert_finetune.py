# -*- coding: utf-8 -*-
"""bert_finetune.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1IhE8wLlD5pxTl61gIAXnPrgSGEiFdJBO

Загрузка данных
"""



import pandas as pd
import numpy as np
from tqdm import tqdm, trange

data = pd.read_csv(#"exampl_main.csv",
                   "exampl_mini.csv", 
                   on_bad_lines='skip',
                   #error_bad_lines= skip,
                   encoding="Windows-1251"
                   #encoding="latin1"
                   ).fillna(method="ffill")
data.tail(10)

"""просмотр данных

Собираем в кортежи для распределения по обуч и тест выборкам
"""

class SentenceGetter(object):

    def __init__(self, data):
        self.n_sent = 3
        self.data = data
        self.empty = False
        #тут был третий тег для разметки pos -p
        agg_func = lambda s: [(w, t) for w,  t in zip(s["Word"].values.tolist(),
                                                           #s["POS"].values.tolist(),
                                                           s["Tag"].values.tolist())]
        self.grouped = self.data.groupby("Sentence#").apply(agg_func)
        self.sentences = [s for s in self.grouped]

    def get_next(self):
        try:
            s = self.grouped["Sentence:{}".format(self.n_sent)]
            self.n_sent += 1
            return s
            
        except:
            return None

getter = SentenceGetter(data)

"""Просмотр слов в предложениях(кортежах)"""

sentences = [[word[0] for word in sentence] for sentence in getter.sentences]
sentences

"""Просмотр тегов в предложениях(кортежах)"""

labels = [[s[1] for s in sentence] for sentence in getter.sentences]
print(labels[14])

tag_values = list(set(data["Tag"].values))
tag_values.append("tag")
tag2idx = {t: i for i, t in enumerate(tag_values)}

print (tag2idx)

print("Number of tags: {}".format(len(data.Tag.unique())))
frequencies = data.Tag.value_counts()
frequencies



"""Подготовка данных 

"""

!pip install transformers

import torch
from torch.utils.data import TensorDataset, DataLoader, RandomSampler, SequentialSampler
from transformers import BertTokenizer, BertConfig

from keras.preprocessing.sequence import pad_sequences
from sklearn.model_selection import train_test_split

torch.__version__

MAX_LEN = 75
bs = 3

torch.cuda.is_available()

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
n_gpu = torch.cuda.device_count()
torch.cuda.get_device_name(0)

tokenizer = BertTokenizer.from_pretrained('bert-base-multilingual-cased', do_lower_case=False)#DeepPavlov/rubert-base-cased

def tokenize_and_preserve_labels(sentence, text_labels):
    tokenized_sentence = []
    labels = []

    for word, label in zip(sentence, text_labels):

        # Tokenize the word and count # of subwords the word is broken into
        tokenized_word = tokenizer.tokenize(word)
        n_subwords = len(tokenized_word)

        # Add the tokenized word to the final tokenized word list
        tokenized_sentence.extend(tokenized_word)

        # Add the same label to the new list of labels `n_subwords` times
        labels.extend([label] * n_subwords)

    return tokenized_sentence, labels

tokenized_texts_and_labels = [
    tokenize_and_preserve_labels(sent, labs)
    for sent, labs in zip(sentences, labels)
]

print (tokenized_texts_and_labels)

tokenized_texts = [token_label_pair[0] for token_label_pair in tokenized_texts_and_labels]
labels = [token_label_pair[1] for token_label_pair in tokenized_texts_and_labels]

input_ids = pad_sequences([tokenizer.convert_tokens_to_ids(txt) for txt in tokenized_texts],
                          maxlen=MAX_LEN, dtype="long", value=0.0,
                          truncating="post", padding="post")

tags = pad_sequences([[tag2idx.get(l) for l in lab] for lab in labels],
                     maxlen=MAX_LEN, value=tag2idx["tag"], padding="post",
                     dtype="long", truncating="post")

attention_masks = [[float(i != 0.0) for i in ii] for ii in input_ids]

tr_inputs, val_inputs, tr_tags, val_tags = train_test_split(input_ids, tags,
                                                            random_state=2018, test_size=0.2)
tr_masks, val_masks, _, _ = train_test_split(attention_masks, input_ids,
                                             random_state=2018, test_size=0.2)

tr_inputs = torch.tensor(tr_inputs)
val_inputs = torch.tensor(val_inputs)
tr_tags = torch.tensor(tr_tags)
val_tags = torch.tensor(val_tags)
tr_masks = torch.tensor(tr_masks)
val_masks = torch.tensor(val_masks)

train_data = TensorDataset(tr_inputs, tr_masks, tr_tags)
train_sampler = RandomSampler(train_data)
train_dataloader = DataLoader(train_data, sampler=train_sampler, batch_size=bs)

valid_data = TensorDataset(val_inputs, val_masks, val_tags)
valid_sampler = SequentialSampler(valid_data)
valid_dataloader = DataLoader(valid_data, sampler=valid_sampler, batch_size=bs)

"""Настройка модели Bert для тонкой настройки"""

import transformers
from transformers import BertForTokenClassification, AdamW

transformers.__version__

from transformers import AutoTokenizer, AutoModelForTokenClassification
from transformers import pipeline

model = BertForTokenClassification.from_pretrained(#"DeepPavlov/rubert-base-cased"
   "bert-base-multilingual-cased",  ## позже заменить на актуальную модель
    #"DeepPavlov/rubert-base-cased",
    #"/content/model.JSON",
    num_labels = len(tag2idx),
    output_attentions = False,
    output_hidden_states = False,
    #use_auth_token=True
)

model.cuda();

FULL_FINETUNING = True
if FULL_FINETUNING:
    param_optimizer = list(model.named_parameters())
    no_decay = ['bias', 'gamma', 'beta']
    optimizer_grouped_parameters = [
        {'params': [p for n, p in param_optimizer if not any(nd in n for nd in no_decay)],
         'weight_decay_rate': 0.01},
        {'params': [p for n, p in param_optimizer if any(nd in n for nd in no_decay)],
         'weight_decay_rate': 0.0}
    ]
else:
    param_optimizer = list(model.classifier.named_parameters())
    optimizer_grouped_parameters = [{"params": [p for n, p in param_optimizer]}]

optimizer = AdamW(
    optimizer_grouped_parameters,
    lr=3e-5, ##3e-5
    eps=1e-5
)

from transformers import get_linear_schedule_with_warmup

epochs = 15
max_grad_norm = 10.0

# Total number of training steps is number of batches * number of epochs.
total_steps = len(train_dataloader) * epochs

# Create the learning rate scheduler.
scheduler = get_linear_schedule_with_warmup(
    optimizer,
    num_warmup_steps=0,
    num_training_steps=total_steps
)

"""Обучение модели для задачи нер

"""

!pip install seqeval

from seqeval.metrics import f1_score, accuracy_score
from seqeval.metrics import f1_score
from sklearn.metrics import f1_score

## Сохраняем средние потери после каждой эпохи, по ним строить график.
loss_values, validation_loss_values = [], []

for _ in trange(epochs, desc="Epoch"):
    # ========================================
    #               Training
    # ========================================
    # Переведим модель в режим обучения.
    model.train()
    # Сброс общей потери за эту эпоху.
    total_loss = 0

    # Training loop
    for step, batch in enumerate(train_dataloader):
        # add batch to gpu
        batch = tuple(t.to(device) for t in batch)
        b_input_ids, b_input_mask, b_labels = batch
        # Always clear any previously calculated gradients before performing a backward pass.
        model.zero_grad()
        # forward pass
        # This will return the loss (rather than the model output)
        # because we have provided the `labels`.
        outputs = model(b_input_ids, token_type_ids=None,
                        attention_mask=b_input_mask, labels=b_labels)
        # get the loss
        loss = outputs[0]
        # Perform a backward pass to calculate the gradients.
        loss.backward()
        # track train loss
        total_loss += loss.item()
        # Clip the norm of the gradient
        # This is to help prevent the "exploding gradients" problem.
        torch.nn.utils.clip_grad_norm_(parameters=model.parameters(), max_norm=max_grad_norm)
        # update parameters
        optimizer.step()
        # Update the learning rate.
        scheduler.step()

    # Calculate the average loss over the training data.
    avg_train_loss = total_loss / len(train_dataloader)
    print("Average train loss: {}".format(avg_train_loss))

    # Store the loss value for plotting the learning curve.
    loss_values.append(avg_train_loss)


    # ========================================
    #               Validation
    # ========================================
    # After the completion of each training epoch, measure our performance on
    # our validation set.

    # Put the model into evaluation mode
    model.eval()
    # Reset the validation loss for this epoch.
    eval_loss, eval_accuracy = 0, 0
    nb_eval_steps, nb_eval_examples = 0, 0
    predictions , true_labels = [], []
    for batch in valid_dataloader:
        batch = tuple(t.to(device) for t in batch)
        b_input_ids, b_input_mask, b_labels = batch

        # Telling the model not to compute or store gradients,
        # saving memory and speeding up validation
        with torch.no_grad():
            # Forward pass, calculate logit predictions.
            # This will return the logits rather than the loss because we have not provided labels.
            outputs = model(b_input_ids, token_type_ids=None,
                            attention_mask=b_input_mask, labels=b_labels)
        # Move logits and labels to CPU
        logits = outputs[1].detach().cpu().numpy()
        label_ids = b_labels.to('cpu').numpy()

        # Calculate the accuracy for this batch of test sentences.
        eval_loss += outputs[0].mean().item()
        predictions.extend([list(p) for p in np.argmax(logits, axis=2)])
        true_labels.extend(label_ids)

    eval_loss = eval_loss / len(valid_dataloader)
    validation_loss_values.append(eval_loss)
    print("Validation loss: {}".format(eval_loss))
    pred_tags = np.array([tag_values[p_i] for p, l in zip(predictions, true_labels)
                                 for p_i, l_i in zip(p, l) if tag_values[l_i] != "PAD"])
    valid_tags = np.array([tag_values[l_i] for l in true_labels
                                  for l_i in l if tag_values[l_i] != "PAD"])
    #F1 = 2 * (pred_tags * valid_tags) / (pred_tags + valid_tags)                                labels=[pos_label]
    print("Validation Accuracy: {}".format(accuracy_score(pred_tags, valid_tags)))
    print("Validation F1-Score-micro: {}".format(f1_score(pred_tags, valid_tags,average='micro')))
    print("Validation F1-Score-macro: {}".format(f1_score(pred_tags, valid_tags,average='macro')))
    print("Validation F1-Score-weighted: {}".format(f1_score(pred_tags, valid_tags,average='weighted')))
    #print("Validation F1-Score-b-per: {}".format(f1_score(pred_tags, valid_tags,labels=['B-PER'])))
    
    print()

"""оценка эксп

"""

!pip install sklearn_crfsuite
!pip install modules
!python -m module install modules.analyze_utils

"""----------------------------------------------------0"""

!pip install datasets

from transformers import AutoModelForTokenClassification, TrainingArguments, Trainer
import numpy as np
from datasets import load_metric
metric = load_metric("seqeval")
def compute_metrics(p):
    predictions, labels = p
    predictions = np.argmax(predictions, axis=2)

    # Remove ignored index (special tokens)
    true_predictions = [
        [label_names[p] for (p, l) in zip(prediction, label) if l != -100]
        for prediction, label in zip(predictions, labels)
    ]
    true_labels = [
        [label_names[l] for (p, l) in zip(prediction, label) if l != -100]
        for prediction, label in zip(predictions, labels)
    ]

    results = metric.compute(predictions=true_predictions, references=true_labels)
    flattened_results = {
        "overall_precision": results["overall_precision"],
        "overall_recall": results["overall_recall"],
        "overall_f1": results["overall_f1"],
        "overall_accuracy": results["overall_accuracy"],
    }
    for k in results.keys():
      if(k not in flattened_results.keys()):
        flattened_results[k+"_f1"]=results[k]["f1"]

    return flattened_results

flattened_results = {"overall_precision": results["overall_precision"],"overall_recall": results["overall_recall"],"overall_f1": results["overall_f1"],"overall_accuracy": results["overall_accuracy"],}

for k in results.keys():
	if(k not in flattened_results.keys()):
    	flattened_results[k+"_f1"]=results[k]["f1"]

"""----------------------------------------"""

from sklearn.metrics import f1_score

res=f1_score(x, valid_tags, average='macro')
print("F1 score:", res)

from seqeval.metrics import classification_report

print(classification_report(labels, predictions))

"""Сохранение модели """

import torch
torch.save(model, '/content/model.bin')

saved_model = torch.load('/content/model.bin')
tokenizer = BertTokenizer.from_pretrained('bert-base-multilingual-cased', do_lower_case=False)

"""или"""

import torch
torch.save(model, '/example_model.bin')
saved_model = torch.load('/example_model.bin')

import torch
torch.cuda.empty_cache()

"""Аналитика к процессу обучения """

# Commented out IPython magic to ensure Python compatibility.
import matplotlib.pyplot as plt
# %matplotlib inline

import seaborn as sns

# Use plot styling from seaborn.
sns.set(style='darkgrid')

# Increase the plot size and font size.
sns.set(font_scale=1.5)
plt.rcParams["figure.figsize"] = (12,6)

# Plot the learning curve.
plt.plot(loss_values, 'b-o', label="training loss")
plt.plot(validation_loss_values, 'r-o', label="validation loss")

# Label the plot.
plt.title("Learning curve")
plt.xlabel("Epoch")
plt.ylabel("Loss")
plt.legend()

plt.show()

"""Тесты

В поселке Маяк Григориопольского района Приднестровья (ПМР) произошло два взрыва, в результате которых были повреждены две вышки связи.

"Из строя выведены две самые мощные антенны: одна мегаваттная, вторая - полумегаваттная. Обе ретранслировали радио РФ. Никто из сотрудников Приднестровского радиоцентра и местных жителей не пострадал", - сообщила пресс-служба МВД.
"""

test_sentence = """
Киностудия заключила кредитное соглашение с ВТБ в 2013г.
"""
#3 декабря 2019 АО "Укртранснафта" и ОАО "Транснефть" заключили дополнительное соглашение к договору о предоставлении услуг по транспортировке нефти по территории Украины, которая продолжает его действие на десять лет – с 1 января 2020 до 1 января 2030 рок", – сообщили в Укртранснафте
#"Авиализинг" и "Гражданские самолеты Сухого" заключили предварительный договор на 630 млн долларов 17 июля 2008
#Соглашения об их поставке были подписаны между Министерством безопасности Аргентины и Министерством обороны Израиля 15 декабря 2016 года.
#Mail.ru Group выходит на рынок наружной рекламы Холдинг уже заключил договор с Gallery и ведет переговоры с другими операторами
#0.12.2011 Вопрос задает Кудрявый Владимир Николаевич г. Старый Оскол 24.11.2011г заключил Пользовательское соглашение для получения доступа в "Личный кабинет"
#Космическое агентство США объявило о заключении трех контрактов с Hughes Aircraft, Space General и Philco на предмет исследования вопросов связанных с созданием контейнеров, которые будут сбрасываться на поверхность Луны с лунной капсулы корабля Апполон.
#По его словам, российский магазин приложений будет готов к лету 2022 года, он будет работать на Android. Аpp Store и Google Play, как сказал премьер, вскоре могут ограничить доступ пользователям из России.

tokenized_sentence = tokenizer.encode(test_sentence)
input_ids = torch.tensor([tokenized_sentence]).cuda()

print (input_ids)

with torch.no_grad():
    output = model(input_ids)
label_indices = np.argmax(output[0].to('cpu').numpy(), axis=2)

# join bpe split tokens
tokens = tokenizer.convert_ids_to_tokens(input_ids.to('cpu').numpy()[0])
new_tokens, new_labels = [], []
for token, label_idx in zip(tokens, label_indices[0]):
    if token.startswith("##"):
        new_tokens[-1] = new_tokens[-1] + token[2:]
    else:
        new_labels.append(tag_values[label_idx])
        new_tokens.append(token)

for token, label in zip(new_tokens, new_labels):
    print("{}\t{}".format(label, token))

"""эксперимент с спэйси"""

!pip install -U spacy
#!pip install -U spacy[cuda100]

!python -m spacy download ru_core_news_sm

!python -m spacy download ru_core_news_sm

import spacy
from spacy.lang.ru.examples import sentences 

nlp = spacy.load('ru_core_news_sm')#"ru_core_news_lg")
doc = nlp("""
0.12.2011 Вопрос задает Кудрявый Владимир Николаевич г. Старый Оскол 24.11.2011г заключил Пользовательское соглашение для получения доступа в "Личный кабинет

""")
for ent in doc.ents:
    print(ent.text, ent.label_)

from spacy import displacy
displacy.render(doc, style='ent', jupyter=True)

!python -m spacy project clone pipelines/tagger_parser_ud

!python -m spacy init base_config\ \(1\).cfg

import spacy
from spacy.tokens import DocBin

nlp = spacy.blank("ru")
training_data = [
  (
      "10.12.2011 Вопрос задает Кудрявый Владимир Николаевич г. Старый Оскол.", [(0, 9, "DATATIME")])
  ]
# the DocBin will store the example documents
db = DocBin()
for text, annotations in training_data:
    doc = nlp(text)
    ents = []
    for start, end, label in annotations:
        span = doc.char_span(start, end, label=label)
        ents.append(span)
    doc.ents = ents
    db.add(doc)
db.to_disk("./train.spacy")

"""@--------------------------------------------------@


"""

import spacy
import pandas as pd
################### Train Spacy NER.###########

TRAIN_DATA = pd.read_csv(#"ner_dataset.csv",
                   "exampl_mini.csv", 
                   on_bad_lines='skip',
                   #error_bad_lines= skip,
                   encoding="Windows-1251"
                   #encoding="latin1"
                   ).fillna(method="ffill")
    #TRAIN_DATA = convert_dataturks_to_spacy("/home/abhishekn/dataturks/entityrecognition/traindata.json")
nlp = spacy.blank('ru')  # create blank Language class
    # create the built-in pipeline components and add them to the pipeline
    # nlp.create_pipe works for built-ins that are registered with spaCy
if 'ner' not in nlp.pipe_names:
    ner = nlp.create_pipe('ner')
    nlp.add_pipe(ner, last=True)
       

    # add labels
for _, annotations in TRAIN_DATA:
   for ent in annotations.get('entities'):
      ner.add_label(ent[2])

    # get names of other pipes to disable them during training
other_pipes = [pipe for pipe in nlp.pipe_names if pipe != 'ner']
with nlp.disable_pipes(*other_pipes):  # only train NER
     optimizer = nlp.begin_training()
for itn in range(10):
    print("Statring iteration " + str(itn))
    random.shuffle(TRAIN_DATA)
    losses = {}
    for text, annotations in TRAIN_DATA:
        nlp.update(
                    [text],  # batch of texts
                    [annotations],  # batch of annotations
                    drop=0.2,  # dropout - make it harder to memorise data
                    sgd=optimizer,  # callable to update weights
                    losses=losses)
print(losses)
