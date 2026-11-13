"""Experimental MMIO loader for axi_fabric_shell ABI v1.

This module is not selected by the deployed fixed-overlay pipeline. A matching,
validated base overlay and generated configuration are required by its caller.
All postprocessing below is performed by the programmed FABulous logic.
"""
import hashlib
import time

MAGIC=0x424d4631
VERSION=0x00010000
CAPACITY=16384


class FabricPostprocessor:
    def __init__(self,overlay,configuration,expected_sha256):
        if not configuration or len(configuration)%4 or len(configuration)>CAPACITY:
            raise ValueError('Invalid prototype configuration length')
        if hashlib.sha256(configuration).hexdigest()!=expected_sha256:
            raise ValueError('Generated FABulous configuration hash mismatch')
        description=overlay.ip_dict.get('fabric_shell',{})
        if description.get('phys_addr')!=0xA0010000:
            raise ValueError('The overlay does not expose the versioned FABulous shell')
        self.mmio=overlay.fabric_shell.mmio
        if self.mmio.read(0)!=MAGIC or self.mmio.read(4)!=VERSION:
            raise ValueError('Unsupported FABulous configuration-port ABI')
        self.mmio.write(8,0)
        time.sleep(0.01)
        self.mmio.write(8,1)
        time.sleep(0.01)
        # The upstream configuration FSM consumes big-endian 32-bit words.
        padded=configuration+bytes(CAPACITY-len(configuration))
        started=time.monotonic()
        for offset in range(0,CAPACITY,4):
            self.mmio.write(12,int.from_bytes(padded[offset:offset+4],'big'))
        accepted=self.mmio.read(16)
        if accepted!=CAPACITY//4:
            raise RuntimeError('Fabric did not acknowledge every configuration word')
        time.sleep(0.01)
        self.mmio.write(20,0x100)
        if self.mmio.read(28)!=0xffff:
            raise RuntimeError('Configured fabric direction bits do not match the generated wrapper')
        self.report={'adapter':'bmlabs-fabric-postprocess-v1','configuration_sha256':expected_sha256,
            'configuration_bytes':len(configuration),'configuration_words':accepted,
            'loader_seconds':round(time.monotonic()-started,4),'shell_magic':MAGIC,'shell_version':VERSION,
            'generated_configuration_loaded':True,'postprocess_location':'ZCU106 PL FABulous fabric'}

    def run(self,raw_outputs):
        results=[]
        for raw_row in raw_outputs:
            if not 1<=len(raw_row)<=32:raise ValueError('Unsupported output count')
            result=[]
            for column,raw in enumerate(raw_row):
                if type(raw)!=int or not -(2**31)<=raw<2**31:raise ValueError('Invalid signed X2 result')
                for shift in (0,8,16,24):
                    self.mmio.write(20,0x200|((raw>>shift)&255))
                self.mmio.write(20,0x300|(column<<11))
                value=0
                for shift in (0,8,16,24):
                    value|=(self.mmio.read(24)&255)<<shift
                    self.mmio.write(20,0x400)
                result.append(value-(2**32) if value&(2**31) else value)
            results.append(result)
        return results
