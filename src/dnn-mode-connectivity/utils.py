import numpy as np
import os
import torch
import torch.nn.functional as F
from tqdm import tqdm
import curves


def l2_regularizer(weight_decay):
    def regularizer(model):
        l2 = 0.0
        for p in model.parameters():
            l2 += torch.sqrt(torch.sum(p ** 2))
        return 0.5 * weight_decay * l2
    return regularizer


def cyclic_learning_rate(epoch, cycle, alpha_1, alpha_2):
    def schedule(iter):
        t = ((epoch % cycle) + iter) / cycle
        if t < 0.5:
            return alpha_1 * (1.0 - 2.0 * t) + alpha_2 * 2.0 * t
        else:
            return alpha_1 * (2.0 * t - 1.0) + alpha_2 * (2.0 - 2.0 * t)
    return schedule


def adjust_learning_rate(optimizer, lr):
    for param_group in optimizer.param_groups:
        param_group['lr'] = lr
    return lr


def save_checkpoint(dir, epoch, name='checkpoint', **kwargs):
    state = {
        'epoch': epoch,
    }
    state.update(kwargs)
    filepath = os.path.join(dir, '%s-%d.pt' % (name, epoch))
    torch.save(state, filepath)


def train(train_loader, model, optimizer, criterion, regularizer=None, lr_schedule=None, loader_type=None):
    loss_sum = 0.0
    correct = 0.0
    print('train', loader_type)
    num_iters = len(train_loader)
    model.train()
    for iter, (input, target) in tqdm(enumerate(train_loader)):
        if lr_schedule is not None:
            lr = lr_schedule(iter / num_iters)
            adjust_learning_rate(optimizer, lr)
        input = input.cuda(async=True)
        if loader_type == 'celeba':
            target = input.cuda(async=True)
        else:
            target = target.cuda(async=True)
        output = model(input)
        loss = criterion(output, target)
        if regularizer is not None:
            loss += regularizer(model)

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        if loader_type == 'celeba':
            loss_sum += loss.item()
        else:
            loss_sum += loss.item() * input.size(0)
        pred = output.data.argmax(1, keepdim=True)

        if iter % 100 == 0:
            print(f'Batch {iter} loss {loss.item()}')

        if loader_type == 'celeba':
            correct = 0.0
        else:
            correct += pred.eq(target.data.view_as(pred)).sum().item()

    if loader_type == 'celeba':
        return {
                'loss': loss_sum / len(train_loader),
                'accuracy': correct * 100.0 / len(train_loader.dataset)
                }
    else:
        return {
            'loss': loss_sum / len(train_loader.dataset),
            'accuracy': correct * 100.0 / len(train_loader.dataset),
        }


def test(test_loader, model, criterion, regularizer=None, loader_type=None, **kwargs):
    loss_sum = 0.0
    nll_sum = 0.0
    correct = 0.0

    model.eval()

    for input, target in tqdm(test_loader):
        input = input.cuda(async=True)
        if loader_type == 'celeba':
            target = input.cuda(async=True)
        else:
            target = target.cuda(async=True)

        output = model(input, **kwargs)
        nll = criterion(output, target)
        loss = nll.clone()
        if regularizer is not None:
            loss += regularizer(model)

        if loader_type == 'celeba':
            nll_sum += nll.item()
            loss_sum += loss.item()
        else:
            nll_sum += nll.item() * input.size(0)
            loss_sum += loss.item() * input.size(0)
        if loader_type == 'celeba':
            correct = 0.0
        else:
            pred = output.data.argmax(1, keepdim=True)
            correct += pred.eq(target.data.view_as(pred)).sum().item()

    if loader_type == 'celeba':
        return {
            'nll': nll_sum / len(test_loader),
            'loss': loss_sum / len(test_loader),
            'accuracy': correct * 100.0 / len(test_loader),
            'image_in': input,
            'image_out': output
        }
    else:
        return {
            'nll': nll_sum / len(test_loader.dataset),
            'loss': loss_sum / len(test_loader.dataset),
            'accuracy': correct * 100.0 / len(test_loader.dataset),
        }



def predictions(test_loader, model, **kwargs):
    model.eval()
    preds = []
    targets = []
    for input, target in test_loader:
        input = input.cuda(async=True)
        output = model(input, **kwargs)
        probs = F.softmax(output, dim=1)
        preds.append(probs.cpu().data.numpy())
        targets.append(target.numpy())
    return np.vstack(preds), np.concatenate(targets)


def isbatchnorm(module):
    return issubclass(module.__class__, torch.nn.modules.batchnorm._BatchNorm) or \
           issubclass(module.__class__, curves._BatchNorm)


def _check_bn(module, flag):
    if isbatchnorm(module):
        flag[0] = True


def check_bn(model):
    flag = [False]
    model.apply(lambda module: _check_bn(module, flag))
    return flag[0]


def reset_bn(module):
    if isbatchnorm(module):
        module.reset_running_stats()


def _get_momenta(module, momenta):
    if isbatchnorm(module):
        momenta[module] = module.momentum


def _set_momenta(module, momenta):
    if isbatchnorm(module):
        module.momentum = momenta[module]


def update_bn(loader, model, **kwargs):
    if not check_bn(model):
        return
    model.train()
    momenta = {}
    model.apply(reset_bn)
    model.apply(lambda module: _get_momenta(module, momenta))
    num_samples = 0
    for input, _ in loader:
        input = input.cuda(async=True)
        batch_size = input.data.size(0)

        momentum = batch_size / (num_samples + batch_size)
        for module in momenta.keys():
            module.momentum = momentum

        model(input, **kwargs)
        num_samples += batch_size

    model.apply(lambda module: _set_momenta(module, momenta))
