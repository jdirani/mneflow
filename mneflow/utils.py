# -*- coding: utf-8 -*-
"""
Created on Thu Dec 28 16:12:48 2017
Read/ Filter 0.1-45Hz/ Epoch/ Downsample/ Get labels/ Shuffle/  Split/ Scale/ Serialize/ Save
mne version = 0.15.2/ python2.7
@author: zubarei1
"""

"pool: 102+101+3+4 (right), and 1+2+103+104(left)"

import mne
import numpy as np
import csv
import tensorflow as tf
import scipy.io as sio


def leave_one_subj_out(h_params,params,data_paths,savepath):
    #TODO: update to use meta/TFRdataset
    results = []
    from models import Model
    for i, (t,v) in enumerate(zip(*data_paths)):
        dp = data_paths.copy()
        holdout = [dp[0].pop(i)]
        model = Model(h_params,params,data_paths,savepath)
        model.train_tfr()
        test_accs = model.evaluate_performance(holdout, batch_size=None)
        prt_test_acc, prt_logits = model.evaluate_realtime(holdout, batch_size=120, step_size=params['test_upd_batch'])
        results.append({'val_acc':model.v_acc[0], 'test_init':np.mean(test_accs), 'test_upd':np.mean(prt_test_acc), 'sid':h_params['sid']})
        logger(savepath,h_params,params,results[-1])
    return results  
    

def plot_cm(y_true,y_pred,classes=None, normalize=False,):
    #TODO: remove sklearn dependency maybe
    from matplotlib import pyplot as plt
    from sklearn.metrics import confusion_matrix
    import itertools
    
    cm = confusion_matrix(y_true, y_pred)
    title='Confusion matrix'
    if normalize:
        cm = cm.astype('float') / cm.sum(axis=1)[:, np.newaxis]

    plt.imshow(cm, interpolation='nearest', cmap=plt.cm.Blues)
    plt.title(title)
    plt.colorbar()
    if not classes:
        classes = np.arange(len(np.unique(y_true)))
    tick_marks = np.arange(len(classes))
    plt.xticks(tick_marks, classes, rotation=45)
    plt.yticks(tick_marks, classes)
    plt.ylabel='True label',
    plt.xlabel='Predicted label'
    fmt = '.2f' if normalize else 'd'
    thresh = cm.max() / 2.
    for i, j in itertools.product(range(cm.shape[0]), range(cm.shape[1])):
        plt.text(j, i, format(cm[i, j], fmt),
                 horizontalalignment="center",
                 color="white" if cm[i, j] > thresh else "black")

    
def logger(savepath,h_params, params, results):
    """Log perfromance"""
    log = dict()
    log.update(h_params)
    log.update(params)
    log.update(results)
    for a in log:
        if hasattr(log[a], '__call__'):
            log[a] = log[a].__name__
    header = ['architecture','sid','val_acc','test_init', 'test_upd', #'train_time',
              'n_epochs','eval_step','n_batch','n_classes','n_ch','n_t',
              'l1_lambda','n_ls','learn_rate','dropout','patience','min_delta',
              'nonlin_in','nonlin_hid','nonlin_out','filter_length','pooling',
              'test_upd_batch', 'stride']
    with open(savepath+'-'.join([h_params['architecture'],'training_log.csv']), 'a') as csv_file:
        writer = csv.DictWriter(csv_file,fieldnames=header)
        #writer.writeheader()
        writer.writerow(log)

def sliding_augmentation(x, labels,seg_len=500,stride=1,scale=False,demean=False):
    n_epochs, n_ch, n_t = x.shape
    nrows = n_t - seg_len + 1            
    a,b,c = x.strides
    x4D = np.lib.stride_tricks.as_strided(x,shape=(n_epochs,n_ch,nrows,seg_len),strides=(a,b,c,c))
    x4D = x4D[:,:,::stride,:]
    labels = np.tile(labels,x4D.shape[2])
    x4D = np.moveaxis(x4D,[2],[0])
    x4D = x4D.reshape([n_epochs*x4D.shape[0],n_ch,seg_len],order='C')
    assert labels.shape[0] == x4D.shape[0]
    if demean:
        x4D -=x4D.mean(1,keepdims=True)
    if scale:
        x4D /=x4D.reshape([x4D.shape[0],-1]).std(-1)[:,None,None]
    return x4D, labels
    
#def scale_type(X,intrvl=36):
#    """Perform scaling based on pre-stimulus baseline"""
#    X0 = X[:,:,:intrvl]
#    X0 = X0.reshape([X.shape[0],-1])
#    X -= X0.mean(-1)[:,None,None]
#    X /= X0.std(-1)[:,None,None]
#    X = X[:,:,intrvl:]
#    return X
    
def scale_to_baseline(X,baseline=None):
    """Perform scaling based on pre-stimulus baseline"""
    if baseline == None:
        interval = np.arange(X.shape[-1])        
    elif isinstance(baseline,int):
        interval = np.arange(baseline)
    elif isinstance(baseline,tuple):
        interval = np.arange(baseline[0],baseline[1])
    X0 = X[:,:,interval]
    if X.shape[1]==306:
        magind = np.arange(2,306,3)
        gradind = np.delete(np.arange(306),magind)
        X0m = X0[:,magind,:].reshape([X0.shape[0],-1])
        X0g = X0[:,gradind,:].reshape([X0.shape[0],-1])
        
        X[:,magind,:] -= X0m.mean(-1)[...,None,None]
        X[:,magind,:] /= X0m.std(-1)[:,None,None]
        X[:,gradind,:] -= X0g.mean(-1)[:,None,None]
        X[:,gradind,:] /= X0g.std(-1)[:,None,None]
    else:      
        X0 = X0.reshape([X.shape[0],-1])
        X -= X0.mean(-1)[:,None,None]
        X /= X0.std(-1)[:,None,None]
    return X
       
def write_tfrecords(X_,y_,output_file):
    writer = tf.python_io.TFRecordWriter(output_file)
    for X,y in zip(X_,y_):
         # Feature contains a map of string to feature proto objects
         feature = {}
         feature['X'] = tf.train.Feature(float_list=tf.train.FloatList(value=X.flatten()))
         feature['y'] = tf.train.Feature(int64_list=tf.train.Int64List(value=y.flatten()))
         # Construct the Example proto object
         example = tf.train.Example(features=tf.train.Features(feature=feature))
         # Serialize the example to a string
         serialized = example.SerializeToString()
         # write the serialized object to the disk
         writer.write(serialized)
    writer.close()
    
    
def split_sets(X,y,val=.1):
    shuffle= np.random.permutation(X.shape[0])
    print(y.shape)
    
    val_size = int(round(val*X.shape[0]))
    print(val_size)
    
    X_val = X[shuffle[:val_size],...]
    y_val = y[shuffle[:val_size],...]
    X_train = X[shuffle[val_size:],...]
    y_train = y[shuffle[val_size:],...]
    return X_train, y_train, X_val, y_val

def produce_labels(y):
    classes, inds, inv, counts = np.unique(y, return_index=True, return_inverse=True, return_counts=True)
    total_counts = np.sum(counts)
    counts = counts/float(total_counts)
    class_proportions = {cls:cnt  for cls, cnt in zip(inds, counts)}
    orig_classes = {new:old for new,old in zip(inv[inds],classes)}
    return  inv, total_counts, class_proportions, orig_classes

    
def produce_tfrecords(inputs,opt):
    """
    Produces TFRecord files from input, applies basic preprocessing
    
    inputs : list of mne.epochs.Epochs or strings
    
    path
    
    """
    meta  = dict(train_paths=[],val_paths=[],orig_paths=[])
    jj = 0
    i = 0
    if not isinstance(inputs,list):
        inputs = [inputs]
    #Import data and labels
    for inp in inputs:
        if isinstance(inp,mne.epochs.Epochs):
            print('processing epochs')
            data = inp.get_data()
            events = inp.events[:,2]
        elif isinstance(inp,str):
            fname = inp#''.join([opt.path,inp])#"filename mess, 1 raw, 2.epochs, 3.array"""
            if opt['input_type'] == 'array':
                if fname[-3:] == 'mat':
                    datafile = sio.loadmat(fname)
                    
                elif fname[-3:] == 'npz':
                    datafile = np.load(fname)
                else:
                    print('Only accept .mat or .npz for array input_type')
                    
                data = datafile[opt['array_keys']['X']]
                events = datafile[opt['array_keys']['y']]
                #raw_y = datafile[opt['array_keys']['y']]            
            
            elif opt['input_type']== 'epochs':
                epochs = mne.epochs.read_epochs(fname)
                events = epochs.events[:,2]
                epochs.pick_types(**opt['picks'])
                data = epochs.get_data()
                #events = events[:,2]
                del epochs
        #IMPORT ENDS HERE!                
                
        #for all Xs and ys regardless of input type
        
        if opt['scale']:
            #TODO: edit scale_type
            data = scale_to_baseline(data,opt['scale_interval'])
            
        #if opt['augment']:
            #print('Not Implemented')
            #data, events = sliding_augmentation(data,events,seg_len=500,stride=7,scale=False,demean=False)
        
        if opt['task']=='classification':
            labels, total_counts, meta['class_proportions'], meta['orig_classes'] = produce_labels(events)
            meta['n_classes'] = len(meta['class_proportions'])
        elif opt['task']=='regression':
            print('Not Implemented')
            #assert y.shape[0]==data.shape[0]
        i +=1
        if i == 1:
            X = data
            y = labels
            print('labels', labels.shape)
        elif i > 1:
            X = np.concatenate([X,data])
            y = np.concatenate([y,labels])         
        print(X.shape)
        
        if i%opt['savebatch']==0 or jj*opt['savebatch']+i==len(inputs):
            print('Saving TFRecord# {}'.format(jj))
            X = X.astype(np.float32)
            n_trials, meta['n_ch'],meta['n_t'] = X.shape          
            X_train, y_train, X_val, y_val = split_sets(X,y,val=opt['val_size'])
            
            meta['train_paths'].append(''.join([opt['savepath'],opt['out_name'],'_train_',str(jj),'.tfrecord']))
            write_tfrecords(X_train,y_train,meta['train_paths'][-1])
            meta['val_paths'].append(''.join([opt['savepath'],opt['out_name'],'_val_',str(jj),'.tfrecord']))
            write_tfrecords(X_val,y_val,meta['val_paths'][-1])
            if opt['save_orig']:
                meta['orig_paths'].append(''.join([opt['savepath'],opt['out_name'],'_orig_',str(jj),'.tfrecord']))
                write_tfrecords(X,y,meta['orig_paths'][-1])
            jj+=1
            i =0
            del X, y
    return meta