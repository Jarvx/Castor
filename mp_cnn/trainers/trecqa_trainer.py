import time

import torch
import torch.nn.functional as F
from torch.optim.lr_scheduler import ReduceLROnPlateau

from mp_cnn.trainers.trainer import Trainer


class TRECQATrainer(Trainer):

    def __init__(self, model, train_loader, trainer_config, train_evaluator, test_evaluator, dev_evaluator=None):
        super(TRECQATrainer, self).__init__(model, train_loader, trainer_config, train_evaluator, test_evaluator, dev_evaluator)

    def train_epoch(self, epoch):
        self.model.train()
        total_loss = 0
        for batch_idx, batch in enumerate(self.train_loader):
            self.optimizer.zero_grad()
            output = self.model(batch.sentence_1, batch.sentence_2, batch.ext_feats)
            loss = F.cross_entropy(output, batch.label, size_average=False)
            total_loss += loss.data[0]
            loss.backward()
            self.optimizer.step()
            if batch_idx % self.log_interval == 0:
                self.logger.info('Train Epoch: {} [{}/{} ({:.0f}%)]\tLoss: {:.6f}'.format(
                    epoch, min(batch_idx * self.batch_size, len(batch.dataset.examples)),
                    len(batch.dataset.examples),
                    100. * batch_idx / (len(self.train_loader)), loss.data[0])
                )

        average_loss, mean_average_precision, mean_reciprocal_rank = self.evaluate(self.train_evaluator, 'train')

        if self.use_tensorboard:
            self.writer.add_scalar('trecqa/train/cross_entropy_loss', average_loss, epoch)
            self.writer.add_scalar('trecqa/train/map', mean_average_precision, epoch)
            self.writer.add_scalar('trecqa/train/mrr', mean_reciprocal_rank, epoch)

        return total_loss

    def train(self, epochs):
        scheduler = ReduceLROnPlateau(self.optimizer, mode='max', factor=self.lr_reduce_factor, patience=self.patience)
        epoch_times = []
        prev_loss = -1
        best_dev_score = -1
        for epoch in range(1, epochs + 1):
            start = time.time()
            self.logger.info('Epoch {} started...'.format(epoch))
            self.train_epoch(epoch)

            dev_scores = self.evaluate(self.dev_evaluator, 'dev')
            new_loss, mean_average_precision, mean_reciprocal_rank = dev_scores

            if self.use_tensorboard:
                self.writer.add_scalar('trecqa/lr', self.optimizer.param_groups[0]['lr'], epoch)
                self.writer.add_scalar('trecqa/dev/cross_entropy_loss', new_loss, epoch)
                self.writer.add_scalar('trecqa/dev/map', mean_average_precision, epoch)
                self.writer.add_scalar('trecqa/dev/mrr', mean_reciprocal_rank, epoch)

            end = time.time()
            duration = end - start
            self.logger.info('Epoch {} finished in {:.2f} minutes'.format(epoch, duration / 60))
            epoch_times.append(duration)

            if dev_scores[0] > best_dev_score:
                best_dev_score = dev_scores[0]
                torch.save(self.model, self.model_outfile)

            if abs(prev_loss - new_loss) <= 0.0002:
                self.logger.info('Early stopping. Loss changed by less than 0.0002.')
                break

            prev_loss = new_loss
            scheduler.step(dev_scores[0])

        self.logger.info('Training took {:.2f} minutes overall...'.format(sum(epoch_times) / 60))