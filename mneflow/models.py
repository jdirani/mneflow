# -*- coding: utf-8 -*-
"""
Defines mneflow.models.Model parent class and the implemented models as its
subclasses. Implemented models inherit basic methods from the parent class.

"""
from .layers import ConvDSV, Dense, vgg_block, LFTConv, VARConv, DeMixing
import tensorflow as tf
import numpy as np
from sklearn.covariance import ledoit_wolf


class Model(object):
    """
    Parent class for all MNEflow models

    Provides fast and memory-efficient data handling and simplified API.
    Custom models can be built by overriding _build_graph and
    set_optimizer methods.

    """
    def __init__(self, Dataset, Optimizer, specs):
        """
        Parameters
        -----------
        Dataset : mneflow.Dataset
                    Dataset object.

        Optimizer : mneflow.Optimizer
                    Optimizer object.

        specs : dict
                dictionary of model-specific hyperparameters. Must include at
                least model_path - path for saving a trained model. See
                subclass definitions for details.

        """

        self.specs = specs
        self.model_path = specs['model_path']
        if Dataset.h_params['task'] == 'classification':
            self.n_classes = Dataset.h_params['n_classes']
        else:
            self.y_shape = Dataset.h_params['y_shape']
        self.fs = Dataset.h_params['fs']
        self.sess = tf.Session()
        self.handle = tf.placeholder(tf.string, shape=[])
        self.train_iter, self.train_handle = self._start_iterator(Dataset.train)
        self.val_iter, self.val_handle = self._start_iterator(Dataset.val)

        self.iterator = tf.data.Iterator.from_string_handle(self.handle, Dataset.train.output_types, Dataset.train.output_shapes)
        self.X, self.y_ = self.iterator.get_next()
        self.rate = tf.placeholder(tf.float32, name='rate')
        self.dataset = Dataset
        self.optimizer = Optimizer

    def _start_iterator(self, Dataset):

        """
        Builds initializable iterator and string handle.
        """

        ds_iterator = Dataset.make_initializable_iterator()
        handle = self.sess.run(ds_iterator.string_handle())
        self.sess.run(ds_iterator.initializer)
        return ds_iterator, handle

    def build(self):

        """
        Compile a model

        """

        # Initialize computational graph
        self.y_pred = self.build_graph()
        print('y_pred:', self.y_pred.shape)
        # Initialize optimizer
        self.saver = tf.train.Saver(max_to_keep=1)
        opt_handles = self.optimizer.set_optimizer(self.y_pred, self.y_)
        self.train_step, self.accuracy, self.cost, self.p_classes = opt_handles
        print('Initialization complete!')

    def build_graph(self):

        """
        Build computational graph using defined placeholder self.X as input

        Can be overriden in a sub-class for customized architecture.

        Returns
        --------
        y_pred : tf.Tensor
                output of the forward pass of the computational graph.
                prediction of the target variable

        """
        print('Specify a model. Set to linear classifier!')
        fc_1 = Dense(size=self.n_classes, nonlin=tf.identity,
                     dropout=self.rate)
        y_pred = fc_1(self.X)
        return y_pred

    def train(self, n_iter, eval_step=250, min_delta=1e-6, early_stopping=3):
        """
        Trains a model

        Parameters
        -----------

        n_iter : int
                maximum number of training iterations.

        eval_step : int
                How often to evaluate model performance during training.

        early_stopping : int
                Patience parameter for early stopping. Specifies the number of
                'eval_step's during which validation cost is allowed to rise
                before training stops.

        min_delta : float
                Convergence threshold for validation cost during training.
                Defaults to 0.
        """
        self.sess.run(tf.global_variables_initializer())
        min_val_loss = np.inf

        patience_cnt = 0
        for i in range(n_iter+1):
            _, t_loss, acc = self.sess.run([self.train_step, self.cost, self.accuracy],
                                           feed_dict={self.handle: self.train_handle,
                                                      self.rate: self.specs['dropout']})
            if i % eval_step == 0:
                self.dataset.train.shuffle(buffer_size=10000)
                self.v_acc, v_loss = self.sess.run([self.accuracy, self.cost],
                                                   feed_dict={self.handle: self.val_handle,
                                                              self.rate: 1.})

                if min_val_loss >= v_loss + min_delta:
                    min_val_loss = v_loss
                    v_acc = self.v_acc
                    self.saver.save(self.sess, ''.join([self.model_path,
                                                        self.scope, '-',
                                                        self.dataset.h_params['data_id']]))
                else:
                    patience_cnt += 1
                    print('* Patience count {}'.format(patience_cnt))
                if patience_cnt >= early_stopping:
                    print("early stopping...")
                    self.saver.restore(self.sess, ''.join([self.model_path,
                                                           self.scope, '-',
                                                           self.dataset.h_params['data_id']]))
                    print('stopped at: epoch %d, val loss %g, val acc %g'
                          % (i,  min_val_loss, v_acc))
                    break
                print('i %d, tr_loss %g, tr_acc %g v_loss %g, v_acc %g'
                      % (i, t_loss, acc, v_loss, self.v_acc))

    def load(self):
        """
        Loads a pretrained model

        To load a specific model the model object should be initialized using
        the corresponding metadata and computational graph
        """

        self.saver.restore(self.sess, ''.join([self.model_path,
                                              self.scope, '-',
                                              self.dataset.h_params['data_id']]))
        self.v_acc = self.sess.run([self.accuracy],
                                   feed_dict={self.handle: self.val_handle})

    def evaluate_performance(self, data_path, batch_size=None):
        """
        Compute performance metric on a TFR dataset specified by path

        Parameters
        ----------
        data_path : str, list of str
                    path to .tfrecords file(s).

        batch_size : NoneType, int
                    whether to split the dataset into batches.
        """
        test_dataset = self.dataset._build_dataset(data_path,
                                                   n_batch=batch_size)
        test_iter, test_handle = self.start_iterator(test_dataset)
        acc = self.sess.run(self.accuracy, feed_dict={self.handle: test_handle,
                                                      self.rate: 1.})
        print('Finished: acc: %g +\\- %g' % (np.mean(acc), np.std(acc)))
        return np.mean(acc)

    def predict(self, data_path, batch_size=None):
        """
        Compute performance metric on a TFR dataset specified by path

        Parameters
        ----------
        data_path : str, list of str
                    path to .tfrecords file(s).

        batch_size : NoneType, int
                    whether to split the dataset into batches.
        """
        if data_path:
            test_dataset = self.dataset._build_dataset(data_path,
                                                       n_batch=batch_size)
            test_iter, test_handle = self.start_iterator(test_dataset)
        else:
            test_iter, test_handle = self.start_iterator(self.dataset.val)
        pred, true = self.sess.run([self.y_pred, self.y_],
                                   feed_dict={self.handle: test_handle,
                                              self.rate: 1.})
        return pred, true

#    def evaluate_realtime(self, data_path, batch_size=None, step_size=1):
#
#        """Compute performance metric on a TFR dataset specified by path
#            batch by batch with updating the model after each batch """
#
#        prt_batch_pred = []
#        prt_logits = []
#        n_test_points = batch_size//step_size
#        count = 0
#
#        test_dataset = tf.data.TFRecordDataset(data_path).map(self._parse_function)
#        test_dataset = test_dataset.batch(step_size)
#        test_iter = test_dataset.make_initializable_iterator()
#        self.sess.run(test_iter.initializer)
#        test_handle = self.sess.run(test_iter.string_handle())
#
#        while True:
#            try:
#                self.load()
#                count += 1
#                preds = 0
#                for jj in range(n_test_points):
#                    pred, probs = self.sess.run([self.correct_prediction,
#                                                self.p_classes],
#                                                feed_dict={self.handle: test_handle,
#                                                           self.rate: 1})
#                    self.sess.run(self.train_step,
#                                  feed_dict={self.handle: test_handle,
#                                             self.rate: self.specs['dropout']})
#                    preds += np.mean(pred)
#                    prt_logits.append(probs)
#                prt_batch_pred.append(preds/n_test_points)
#            except tf.errors.OutOfRangeError:
#                print('prt_done: count: %d, acc: %g +\\- %g'
#                      % (count, np.mean(prt_batch_pred), np.std(prt_batch_pred)))
#                break
#        return prt_batch_pred, np.concatenate(prt_logits)

    def plot_cm(self, dataset='validation', class_names=None, normalize=False):

        """
        Plot a confusion matrix

        Parameters
        ----------

        dataset : str {'training', 'validation'}
                which dataset to use for plotting confusion matrix

        class_names : list of str, optional
                if provided subscribes the classes, otherwise class labels
                are used

        normalize : bool
                whether to return percentages (if True) or counts (False)
        """

        from matplotlib import pyplot as plt
        from sklearn.metrics import confusion_matrix
        import itertools
        if dataset == 'validation':
            feed_dict = {self.handle: self.val_handle, self.rate: 1.}
        elif dataset == 'training':
            feed_dict = {self.handle: self.train_handle, self.rate: 1.}
        y_true, y_pred = self.sess.run([self.y_, self.p_classes],
                                       feed_dict=feed_dict)
        y_pred = np.argmax(y_pred, 1)
        f = plt.figure()
        cm = confusion_matrix(y_true, y_pred)
        title = 'Confusion matrix'
        if normalize:
            cm = cm.astype('float') / cm.sum(axis=1)[:, np.newaxis]

        plt.imshow(cm, interpolation='nearest', cmap=plt.cm.Blues)
        plt.title(title)
        ax = f.gca()
        ax.set_ylabel('True label')
        ax.set_xlabel('Predicted label')
        plt.colorbar()
        if not class_names:
            class_names = np.arange(len(np.unique(y_true)))
        tick_marks = np.arange(len(class_names))
        plt.xticks(tick_marks, class_names, rotation=45)
        plt.yticks(tick_marks, class_names)

        fmt = '.2f' if normalize else 'd'
        thresh = cm.max() / 2.
        for i, j in itertools.product(range(cm.shape[0]), range(cm.shape[1])):
            plt.text(j, i, format(cm[i, j], fmt),
                     horizontalalignment="center",
                     color="white" if cm[i, j] > thresh else "black")
        return f


class VGG19(Model):
    """
    VGG-19 model.

    References
    ----------

    """
    def __init__(self, Dataset, params, specs):
        super().__init__(Dataset, params)
        self.specs = dict(n_ls=self.params['n_ls'], nonlin_out=tf.nn.relu,
                          inch=1, padding='SAME', filter_length=(3, 3),
                          domain='2d', stride=1, pooling=1, conv_type='2d')
        self.scope = 'vgg19'

    def build_graph(self):
        X1 = tf.expand_dims(self.X, -1)
        if X1.shape[1] == 306:
            X1 = tf.concat([X1[:, 0:306:3, :],
                            X1[:, 1:306:3, :],
                            X1[:, 2:306:3, :]], axis=3)
            self.specs['inch'] = 3

        vgg1 = vgg_block(2, ConvDSV, self.specs)
        out1 = vgg1(X1)

        self.specs['inch'] = self.specs['n_ls']
        self.specs['n_ls'] *= 2
        vgg2 = vgg_block(2, ConvDSV, self.specs)
        out2 = vgg2(out1)
#
        self.specs['inch'] = self.specs['n_ls']
        self.specs['n_ls'] *= 2
        vgg3 = vgg_block(4, ConvDSV, self.specs)
        out3 = vgg3(out2)

        self.specs['inch'] = self.specs['n_ls']
        self.specs['n_ls'] *= 2
        vgg4 = vgg_block(4, ConvDSV, self.specs)
        out4 = vgg4(out3)
#
        self.specs['inch'] = self.specs['n_ls']
        vgg5 = vgg_block(4, ConvDSV, self.specs)
        out5 = vgg5(out4)

#
        fc_1 = Dense(size=4096, nonlin=tf.nn.relu, dropout=self.rate)
        fc_2 = Dense(size=4096, nonlin=tf.nn.relu, dropout=self.rate)
        fc_out = Dense(size=self.n_classes, nonlin=tf.identity,
                       dropout=self.rate)
        y_pred = fc_out(fc_2(fc_1(out5)))
        return y_pred


class EEGNet(Model):
    """EEGNet

    Parameters
    ----------
    eegnet_params : dict

    n_ls : int
            number of (temporal) convolution kernrels in the first layer.
            Defaults to 8

    filter_length : int
                    length of temporal filters in the first layer.
                    Defaults to 32

    stride : int
             stride of the average polling layers. Defaults to 4.

    pooling : int
              pooling factor of the average polling layers. Defaults to 4.

    References
    ----------
    [1] V.J. Lawhern, et al., EEGNet: A compact convolutional neural network
    for EEG-based brain–computer interfaces 10 J. Neural Eng., 15 (5) (2018),
    p. 056013

    [2]  Original  EEGNet implementation by the authors can be found at
    https://github.com/vlawhern/arl-eegmodels
    """

    def build_graph(self):
        self.scope = 'eegnet'

        X1 = tf.expand_dims(self.X, -1)
        vc1 = ConvDSV(n_ls=self.specs['n_ls'], nonlin_out=tf.identity, inch=1,
                      filter_length=self.specs['filter_length'], domain='time',
                      stride=1, pooling=1, conv_type='2d')
        vc1o = vc1(X1)
        bn1 = tf.layers.batch_normalization(vc1o)
        dwc1 = ConvDSV(n_ls=1, nonlin_out=tf.identity, inch=self.specs['n_ls'],
                       padding='VALID', filter_length=bn1.get_shape()[1].value,
                       domain='space',  stride=1, pooling=1,
                       conv_type='depthwise')
        dwc1o = dwc1(bn1)
        bn2 = tf.layers.batch_normalization(dwc1o)
        out2 = tf.nn.elu(bn2)
        out22 = tf.nn.dropout(out2, self.rate)

        sc1 = ConvDSV(n_ls=self.specs['n_ls'], nonlin_out=tf.identity,
                      inch=self.specs['n_ls'],
                      filter_length=self.specs['filter_length']//4,
                      domain='time', stride=1, pooling=1,
                      conv_type='separable')

        sc1o = sc1(out22)
        bn3 = tf.layers.batch_normalization(sc1o)
        out3 = tf.nn.elu(bn3)
        out4 = tf.nn.avg_pool(out3, [1, 1, self.specs['pooling'], 1],
                              [1, 1, self.specs['stride'], 1], 'SAME')
        out44 = tf.nn.dropout(out4, self.rate)

        sc2 = ConvDSV(n_ls=self.specs['n_ls']*2, nonlin_out=tf.identity,
                      inch=self.specs['n_ls'],
                      filter_length=self.specs['filter_length']//4,
                      domain='time', stride=1, pooling=1,
                      conv_type='separable')
        sc2o = sc2(out44)
        bn4 = tf.layers.batch_normalization(sc2o)
        out5 = tf.nn.elu(bn4)
        out6 = tf.nn.avg_pool(out5, [1, 1, self.specs['pooling'], 1],
                              [1, 1, self.specs['stride'], 1], 'SAME')
        out66 = tf.nn.dropout(out6, self.rate)

        out7 = tf.reshape(out66, [-1, np.prod(out66.shape[1:])])
        fc_out = Dense(size=self.n_classes, nonlin=tf.identity,
                       dropout=self.rate)
        y_pred = fc_out(out7)
        return y_pred


class LFCNN(Model):

    """
    LF-CNN. Includes basic paramter interpretation options.

    For details see [1].

    Parameters
    ----------
    n_ls : int
        number of latent components
        Defaults to 32

    filter_length : int
        length of spatio-temporal kernels in the temporal
        convolution layer. Defaults to 7

    stride : int
        stride of the max pooling layer. Defaults to 1

    pooling : int
        pooling factor of the max pooling layer. Defaults to 2

    References
    ----------
        [1]  I. Zubarev, et al., Adaptive neural network classifier for
        decoding MEG signals. Neuroimage. (2019) May 4;197:425-434
        """

    def build_graph(self):
        """
        Build computational graph using defined placeholder self.X as input

        Returns
        --------
        y_pred : tf.Tensor
                output of the forward pass of the computational graph.
                prediction of the target variable

        """
        self.scope = 'var-cnn'
        self.demix = DeMixing(n_ls=self.specs['n_ls'])

        self.tconv1 = LFTConv(scope="conv", n_ls=self.specs['n_ls'],
                              nonlin_out=tf.nn.relu,
                              filter_length=self.specs['filter_length'],
                              stride=self.specs['stride'],
                              pooling=self.specs['pooling'],
                              padding=self.specs['padding'])

        self.fin_fc = Dense(size=self.n_classes,
                            nonlin=tf.identity, dropout=self.rate)

        y_pred = self.fin_fc(self.tconv1(self.demix(self.X)))
        return y_pred

    def plot_out_weihts(self,):
        """
        Plots the weights of the output layer

        """
        from matplotlib import pyplot as plt

        f, ax = plt.subplots(1, self.n_classes)
        for i in range(self.n_classes):
            F = self.out_weights[..., i]
            times = self.specs['stride']*np.arange(F.shape[-1])/float(self.fs)
            t_step = np.diff(times)[0]
            pat, t = np.where(F == np.max(F))
            ax[i].pcolor(times, np.arange(self.specs['n_ls']), F, cmap='bone_r')
            ax[i].plot(times[t]+.5*t_step, pat+.5, markeredgecolor='red',
                       markerfacecolor='none', marker='s', markersize=10,
                       markeredgewidth=2)
        plt.show()

    def compute_patterns(self, megdata=None, output='patterns'):
        """
        Computes spatial patterns from filter weights.

        Required for visualization.
        """

        vis_dict = {self.handle: self.train_handle, self.rate: 1}
        spatial = self.sess.run(self.demix.W, feed_dict=vis_dict)
        self.filters = np.squeeze(self.sess.run(self.tconv1.filters,
                                                feed_dict=vis_dict))
        self.patterns = spatial

        if 'patterns' in output:
            data = self.sess.run(self.X, feed_dict=vis_dict)
            data = data.transpose([0, 2, 1])
            data = data.reshape([-1, data.shape[-1]])
            self.dcov, _ = ledoit_wolf(data)
            self.patterns = np.dot(self.dcov, self.patterns)
        if 'full' in output:
            lat_cov, _ = ledoit_wolf(np.dot(data, spatial))
            self.lat_prec = np.linalg.inv(lat_cov)
            self.patterns = np.dot(self.patterns, self.lat_prec)
        self.out_weights, self.out_biases = self.sess.run([self.fin_fc.w, self.fin_fc.b], feed_dict=vis_dict)
        self.out_weights = np.reshape(self.out_weights,
                                      [self.specs['n_ls'], -1, self.n_classes])

    def plot_patterns(self, sensor_layout='Vectorview-grad', sorting='l2',
                      spectra=True, fs=None, scale=False, names=False):
        """
        Plot informative spatial activations patterns for each class of stimuli

        Parameters
        ----------

        sensor_layout : str or mne.channels.Layout
            sensor layout. See mne.channels.read_layout for details

        sorting : str, optional

        spectra : bool, optional
            If True will also plot frequency responses of the associated
            temporal filters. Defaults to False

        fs : float
            sampling frequency

        scale : bool, otional
            If True will min-max scale the output. Defaults to False

        names : list of str, optional
            Class names

        Returns
        -------

        Figure

        """
        from mne import channels, evoked, create_info
        import matplotlib.pyplot as plt
        from scipy.signal import freqz
        self.ts = []
        lo = channels.read_layout(sensor_layout)
        info = create_info(lo.names, 1., sensor_layout.split('-')[-1])
        self.fake_evoked = evoked.EvokedArray(self.patterns, info)
        nfilt = min(self.specs['n_ls']//self.n_classes, 8)
        if sorting == 'l2':
            order = np.argsort(np.linalg.norm(self.patterns, axis=0, ord=2))
        elif sorting == 'l1':
            order = np.argsort(np.linalg.norm(self.patterns, axis=0, ord=1))
        elif sorting == 'contribution':
            nfilt = 3
            order = []
            for i in range(self.n_classes):
                inds = np.argsort(self.out_weights[..., i].sum(-1))[::-1]
                order += list(inds[:nfilt])
            order = np.array(order)
        elif sorting == 'abs':
            nfilt = self.n_classes
            order = []
            for i in range(self.n_classes):
                pat = np.argmax(np.abs(self.out_weights[..., i].sum(-1)))
                order.append(pat)
            order = np.array(order)
        elif sorting == 'best':
            nfilt = self.n_classes
            order = []
            for i in range(self.n_classes):
                pat, t = np.where(self.out_weights[..., i] == np.max(self.out_weights[..., i]))
                order.append(pat[0])
                self.ts.append(t)
            order = np.array(order)
        elif sorting == 'best_neg':
            nfilt = self.n_classes
            order = []
            for i in range(self.n_classes):
                pat = np.argmin(self.out_weights[..., i].sum(-1))
                order.append(pat)
        elif sorting == 'worst':
            nfilt = self.n_classes
            order = []
            weight_sum = np.sum(np.abs(self.out_weights).sum(-1), -1)
            pat = np.argsort(weight_sum)
            order = np.array(pat[:nfilt])

        elif isinstance(sorting, list):
            nfilt = len(sorting)
            order = np.array(sorting)
        else:
            order = np.arange(self.specs['n_ls'])
        self.fake_evoked.data[:, :len(order)] = self.fake_evoked.data[:, order]
        if scale:
            self.fake_evoked.data[:, :len(order)] /= self.fake_evoked.data[:, :len(order)].max(0)
        self.fake_evoked.data[:, len(order):] *= 0
        self.out_filters = self.filters[:, order]
        order = np.array(order)
        if spectra:
            z = 2
        else:
            z = 1
        nrows = max(1, len(order)//nfilt)
        ncols = min(nfilt, len(order))

        f, ax = plt.subplots(z*nrows, ncols, sharey=True)
#        f.set_size_inches([16,9])
        ax = np.atleast_2d(ax)
        for i in range(nrows):
            if spectra:
                for jj, flt in enumerate(self.out_filters[:, i*ncols:(i+1)*ncols].T):
                    w, h = freqz(flt, 1)
                    ax[z*i+1, jj].plot(w/np.pi*self.fs/2, np.abs(h))

            self.fake_evoked.plot_topomap(times=np.arange(i*ncols,  (i+1)*ncols, 1.),
                                          axes=ax[z*i], colorbar=False,
                                          vmax=np.percentile(self.fake_evoked.data[:, :len(order)], 99),
                                          scalings=1, time_format='class # %g',
                                          title='Informative patterns ('+sorting+')')
        return f


class VARCNN(Model):

    """VAR-CNN

    For details see [1].

    Parameters
    ----------
    n_ls : int
        number of latent components
        Defaults to 32

    filter_length : int
        length of spatio-temporal kernels in the temporal
        convolution layer. Defaults to 7

    stride : int
        stride of the max pooling layer. Defaults to 1

    pooling : int
        pooling factor of the max pooling layer. Defaults to 2

    References
    ----------
        [1]  I. Zubarev, et al., Adaptive neural network classifier for
        decoding MEG signals. Neuroimage. (2019) May 4;197:425-434
        """

    def build_graph(self):
        self.scope = 'var-cnn'
        self.demix = DeMixing(n_ls=self.specs['n_ls'])

        self.tconv1 = VARConv(scope="conv", n_ls=self.specs['n_ls'],
                              nonlin_out=tf.nn.relu,
                              filter_length=self.specs['filter_length'],
                              stride=self.specs['stride'],
                              pooling=self.specs['pooling'],
                              padding=self.specs['padding'])

        self.fin_fc = Dense(size=self.n_classes,
                            nonlin=tf.identity, dropout=self.rate)

        y_pred = self.fin_fc(self.tconv1(self.demix(self.X)))

        return y_pred


#class VARCNN2(Model):
#
#    """VAR-CNN
#
#    Parameters
#    ----------
#    n_ls : int
#        number of latent components
#        Defaults to 32
#
#    filter_length : int
#        length of spatio-temporal kernels in the temporal
#        convolution layer. Defaults to 7
#
#    stride : int
#        stride of the max pooling layer. Defaults to 1
#
#    pooling : int
#        pooling factor of the max pooling layer. Defaults to 2
#
#    """
#
#    def build_graph(self):
#        self.scope = 'var2'
#        self.demix = DeMixing(n_ls=self.specs['n_ls'])
#
#        self.tconv1 = VARConv(scope="conv", n_ls=self.specs['n_ls'],
#                              nonlin_out=tf.nn.relu,
#                              filter_length=self.specs['filter_length']//2,
#                              stride=self.specs['stride']//2,
#                              pooling=self.specs['pooling']//2,
#                              padding=self.specs['padding'])
#        self.tconv2 = VARConv(scope="conv", n_ls=self.specs['n_ls']//2,
#                              nonlin_out=tf.nn.relu,
#                              filter_length=self.specs['filter_length']//4,
#                              stride=self.specs['stride']//4,
#                              pooling=self.specs['pooling']//4,
#                              padding=self.specs['padding'])
#
#        self.fin_fc = Dense(size=self.n_classes,
#                            nonlin=tf.identity, dropout=self.rate)
#
#        y_pred = self.fin_fc(self.tconv2(self.tconv1(self.demix(self.X))))
#        return y_pred
