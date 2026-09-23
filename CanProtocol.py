class CanData:
            can_id = ''
            Name =''
            Description =''
            Units = 'Deg'
            DataType = ''
            Start = 0
            End = 1
            Freq = 0
            MinVal = 0
            ValueMin = 0
            MaxVal = 255
            ValueMax = 150        

            def __init__(self, can_id, Name, Description, Units, DataType, Start, End, Freq, MinVal, ValueMin, MaxVal, ValueMax):
                self.can_id = can_id
                self.Name = Name
                self.Description = Description
                self.Units = Units
                self.DataType = DataType
                self.Start = Start
                self.End = End 
                self.Freq = Freq 
                self.MinVal = MinVal 
                self.ValueMin = ValueMin
                self.MaxVal = MaxVal 
                self.ValueMax = ValueMax
                

class CanTool:
    
            CanTab = {}
            Temp = 0.0
            Volt = 0.0
            Map = 0.0
            Lambda1 = 0.0
            Lambda2 = 0.0
            Air = 0.0
            Fuel = 0.0 
            Rpm = 0
            Tps = 0
            canid = ""
            
            
            def __init__ (self):
                self.CanTab.update({'TH2o': CanData('30B','TH2o', 'Coolant Temperature', 'DegC', 'uchar', 0, 1, 6, 0, 10, 255, 150 )})
                self.CanTab.update({'VBATT': CanData('308','VBATT', 'Battery Voltage', 'Volt', 'ushort', 0, 2, 12, 0, 0, 1023, 16 )})
                self.CanTab.update({'MAP': CanData('300','MAP', 'Manifold Air Pressure', 'mBar', 'ushort', 4, 2, 50, 0, 0, 1000, 1000 )})
                self.CanTab.update({'Lambda1': CanData('305','Lambda1', 'Actual Measure Lambda Bank1', '', 'uchar', 0, 1, 25, 0, 0, 255, 2 )})
                self.CanTab.update({'Lambda2': CanData('301','Lambda2', 'Actual Measure Lambda Bank2', '', 'uchar', 2, 1, 25, 0, 0, 255, 2 )})
                
            def decode(self, message):
                
                if message:

                    canid = message[0:3]
                    data = message[4:]
                    #print("mess:", message, "canid:",canid," message:",data)
                    if ( canid == '300' ):
                        val = float(int(data[8:10],16)*256+int(data[10:12],16))
                        self.Map = val/1000
                        val = int(data[0:2],16)*256+int(data[2:4],16)
                        self.Rpm = val
                        val = int(data[4:6],16)*100/255
                        self.Tps = val
                    if ( canid == '301' ):
                        self.Lambda2 = float(int(data[4:6],16))*2*14.7/255
                    if ( canid == '305' ):
                        self.Lambda1=  float(int(data[0:2],16))*2*14.7/255
                    if ( canid == '306' ):
                        self.Fuel = float(int(data[12:14],16)*256+int(data[14:16],16))*0.1
                    if ( canid == '308'):
                        val = 0.0
                        val = float(int(data[0:2],16)*256+int(data[2:4],16))
                        self.Volt = val
                        self.Volt = self.Volt*18/1000
                    if ( canid == '30b'):
                        self.Temp = float((int(data[0:2],16)*160))/255-10
                        self.Air = float((int(data[6:8],16)*160))/255-10

                    
                    
                    
                
        

