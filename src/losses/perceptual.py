import torch
import torchvision
# code is inspired by implementation: https://gist.github.com/alper111/8233cdb0414b4cb5853f2f730ab95a49

class VGGPerceptualLoss(torch.nn.Module):
    def __init__(self, feature_loss_func, resize=True, vgg='16'): # TODO: add vgg='19'
        super(VGGPerceptualLoss, self).__init__()
        blocks = []
        blocks.append(torchvision.models.vgg16(pretrained=True).features[:4].eval())
        blocks.append(torchvision.models.vgg16(pretrained=True).features[4:9].eval())
        blocks.append(torchvision.models.vgg16(pretrained=True).features[9:16].eval())
        blocks.append(torchvision.models.vgg16(pretrained=True).features[16:23].eval())
        for bl in blocks:
            for p in bl.parameters():
                p.requires_grad = False
        self.blocks = torch.nn.ModuleList(blocks)
        self.transform = torch.nn.functional.interpolate
        self.resize = resize
        self.feature_loss_func = feature_loss_func

    def forward(self, input, target, feature_layers=[0, 1, 2, 3]):
        if input.shape[1] != 3:
            input = input.repeat(1, 3, 1, 1)
            target = target.repeat(1, 3, 1, 1)
        if self.resize:
            input = self.transform(input, mode='bilinear', size=(224, 224), align_corners=False)
            target = self.transform(target, mode='bilinear', size=(224, 224), align_corners=False)
        
        loss = 0.0
        x = input
        y = target
        for i, block in enumerate(self.blocks):
            x = block(x)
            y = block(y)
            loss += feature_loss_func(x, y) / (x.shape[2] * x.shape[3])
        return loss
